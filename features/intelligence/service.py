from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import asdict, is_dataclass
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from database.repositories import CandleRepository
from database.repositories import MarketIntelligenceRepository
from data_sources.resampler import MarketDataResampler
from config.settings import load_yaml
from features.candles import candle_close_time
from features.intelligence.engine import MarketIntelligenceEngine
from features.intelligence.models import MarketStateSnapshot


class MarketIntelligenceService:
    def __init__(self, session: Session):
        self.session = session
        self.engine = MarketIntelligenceEngine()
        self.resampler = MarketDataResampler()
        self.sample_sources = tuple(load_yaml().get("market_data", {}).get("sample_sources", ("local_csv",)))

    def calculate(self, symbol: str, *, as_of: datetime | None = None) -> MarketStateSnapshot:
        symbol = symbol.upper()
        repository = CandleRepository(self.session)
        native = {
            timeframe: repository.recent_chronological(
                symbol=symbol, timeframe=timeframe, closed_only=True, as_of=as_of, limit=2000,
                exclude_sources=self.sample_sources,
            )
            for timeframe in self.engine.TIMEFRAMES
        }
        if as_of is None:
            close_times = [candle_close_time(rows[-1]) for rows in native.values() if rows]
            as_of = max(close_times) if close_times else datetime.now(timezone.utc)
        for source, target in (("M1", "M5"), ("M5", "M15"), ("M15", "H1"), ("H1", "H4"), ("H4", "D1")):
            if not native[target] and native[source]:
                native[target] = self.resampler.resample(native[source], source, target, as_of=as_of)
        return self.engine.calculate(symbol, native, as_of=as_of)

    def persist(self, snapshot: MarketStateSnapshot) -> int:
        repository = MarketIntelligenceRepository(self.session)
        common = {
            "event_timestamp": snapshot.timestamp, "symbol": snapshot.symbol,
            "calculation_version": snapshot.calculation_version,
            "bias": snapshot.bias.value, "trade_state": snapshot.trade_state,
            "market_candle_id": None,
        }
        repository.upsert({
            **common, "timeframe": "MTF", "snapshot_json": self._jsonable(snapshot),
            "feature_vector_json": self._jsonable(snapshot.feature_vector),
        })
        for timeframe, state in snapshot.timeframes.items():
            if not state.available:
                continue
            candidates = CandleRepository(self.session).recent_chronological(
                symbol=snapshot.symbol, timeframe=timeframe, closed_only=True,
                as_of=state.timestamp, limit=2,
            )
            source_candle = next(
                (row for row in reversed(candidates) if candle_close_time(row) <= state.timestamp), None,
            )
            repository.upsert({
                **common, "timeframe": timeframe,
                "market_candle_id": source_candle.id if source_candle else None,
                "snapshot_json": self._jsonable(state),
                "feature_vector_json": {},
            })
        return 1 + sum(state.available for state in snapshot.timeframes.values())

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        if is_dataclass(value):
            return cls._jsonable(asdict(value))
        if isinstance(value, dict):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._jsonable(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, Enum):
            return value.value
        return value
