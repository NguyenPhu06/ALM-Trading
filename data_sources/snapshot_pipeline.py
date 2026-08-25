from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy.orm import Session

from data_quality import validate_candle_batch
from data_sources.market_data import MarketDataProvider
from data_sources.resampler import MarketDataResampler
from database.repositories import CandleRepository
from features.candles import candle_close_time
from features.intelligence import MarketIntelligenceEngine, MarketIntelligenceService, MarketStateSnapshot


@dataclass(frozen=True, slots=True)
class HistoricalFeaturePipelineReport:
    symbol: str
    as_of: datetime
    rows_received: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    snapshot_rows: int
    snapshot: MarketStateSnapshot


class HistoricalFeaturePipeline:
    """raw/provider -> validation -> normalized candles -> MTF -> snapshot -> database."""

    def __init__(self, session: Session, provider: MarketDataProvider):
        self.session = session
        self.provider = provider
        self.resampler = MarketDataResampler()
        self.engine = MarketIntelligenceEngine()

    def run(
        self, symbol: str, *, timeframes: Sequence[str] = ("D1", "H4", "H1", "M30", "M15", "M5"),
        as_of: datetime | None = None, limit: int = 2000,
    ) -> HistoricalFeaturePipelineReport:
        data = {}
        received = inserted = updated = skipped = 0
        repository = CandleRepository(self.session)
        staged = []
        for timeframe in timeframes:
            rows = self.provider.get_candles(symbol, timeframe, limit=limit)
            if any(row["symbol"] != symbol.upper() or row["timeframe"] != timeframe for row in rows):
                raise ValueError("provider returned timestamp/symbol/timeframe-mismatched candles")
            validate_candle_batch(rows)
            data[timeframe] = rows
            received += len(rows)
            staged.extend(rows)
        result = repository.upsert_many(staged)
        inserted, updated = result.inserted, result.updated
        skipped = result.skipped + result.duplicates_in_batch
        as_of = as_of or max(
            (candle_close_time(rows[-1]) for rows in data.values() if rows),
            default=datetime.now(timezone.utc),
        )
        for source, target in (("M15", "M30"), ("M15", "H1"), ("H1", "H4"), ("H4", "D1")):
            if not data.get(target) and data.get(source):
                data[target] = self.resampler.resample(data[source], source, target, as_of=as_of)
        snapshot = self.engine.calculate(symbol, data, as_of=as_of)
        snapshot_rows = MarketIntelligenceService(self.session).persist(snapshot)
        return HistoricalFeaturePipelineReport(
            symbol.upper(), as_of, received, inserted, updated, skipped, snapshot_rows, snapshot,
        )
