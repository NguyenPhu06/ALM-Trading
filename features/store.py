from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from features.candles import candle_close_time, candle_is_closed
from features.intelligence import FeatureVector, MarketIntelligenceEngine, MarketIntelligenceService, MarketStateSnapshot


@dataclass(frozen=True, slots=True)
class CandleFeatureRecord:
    timestamp: datetime
    symbol: str
    timeframe: str
    features: FeatureVector
    snapshot: MarketStateSnapshot
    calculation_version: str = "phase3.v1"


class FeatureStore:
    """Creates one causal, versioned feature vector per closed base candle."""

    def __init__(self, session: Session | None = None):
        self.session = session
        self.engine = MarketIntelligenceEngine()

    def generate(
        self, symbol: str, candles_by_timeframe: Mapping[str, Sequence[Any]], *, base_timeframe: str = "M5",
    ) -> list[CandleFeatureRecord]:
        base = [row for row in candles_by_timeframe.get(base_timeframe, ()) if candle_is_closed(row)]
        output = []
        for candle in base:
            timestamp = candle_close_time(candle)
            snapshot = self.engine.calculate(symbol, candles_by_timeframe, as_of=timestamp)
            output.append(CandleFeatureRecord(
                timestamp, symbol.upper(), base_timeframe, snapshot.feature_vector, snapshot,
            ))
        return output

    def persist(self, records: Sequence[CandleFeatureRecord]) -> int:
        if self.session is None:
            raise ValueError("FeatureStore persistence requires a database session")
        service = MarketIntelligenceService(self.session)
        return sum(service.persist(record.snapshot) for record in records)
