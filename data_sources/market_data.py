from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from data_sources.normalizer import CandleNormalizer, normalize_symbol, normalize_timeframe


class MarketDataProvider(ABC):
    @abstractmethod
    def get_candles(self, symbol: str, timeframe: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    def get_latest(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        rows = self.get_candles(symbol, timeframe, limit=1)
        return rows[-1] if rows else None


class LocalCsvProvider(MarketDataProvider):
    def __init__(self, path: str | Path, normalizer: CandleNormalizer | None = None):
        self.path = Path(path)
        self.normalizer = normalizer or CandleNormalizer()

    def get_candles(self, symbol: str, timeframe: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        normalized_symbol = normalize_symbol(symbol)
        normalized_timeframe = normalize_timeframe(timeframe)
        frame = pd.read_csv(self.path, dtype=str)
        required = {"timestamp", "open", "high", "low", "close"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"sample CSV missing columns: {', '.join(sorted(missing))}")
        rows: list[dict[str, Any]] = []
        for raw in frame.to_dict(orient="records"):
            raw["symbol"] = raw.get("symbol") or normalized_symbol
            raw["timeframe"] = raw.get("timeframe") or normalized_timeframe
            raw["is_closed"] = True
            rows.append(self.normalizer.normalize(raw, source="local_csv"))
        rows.sort(key=lambda row: row["timestamp"])
        return rows[-limit:] if limit is not None else rows


class CSVProvider(LocalCsvProvider):
    """Explicit Phase 3 name for the read-only local CSV adapter."""


class MockProvider(MarketDataProvider):
    """Deterministic in-memory provider for tests; it never manufactures rows."""

    def __init__(self, rows: Sequence[dict[str, Any]]):
        self.rows = list(rows)

    def get_candles(self, symbol: str, timeframe: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        symbol, timeframe = normalize_symbol(symbol), normalize_timeframe(timeframe)
        rows = sorted(
            (row for row in self.rows if normalize_symbol(row.get("symbol")) == symbol and normalize_timeframe(row.get("timeframe")) == timeframe),
            key=lambda row: row["timestamp"],
        )
        return list(rows[-limit:] if limit is not None else rows)


class MT5Provider(MarketDataProvider):
    """Interface placeholder. Live MT5 connectivity is intentionally absent."""
    def get_candles(self, symbol: str, timeframe: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError("MT5 connectivity is not implemented in Phase 1A")


class BrokerProvider(MT5Provider):
    """Read-only future broker market-data interface; contains no order methods."""


class ExchangeProvider(MT5Provider):
    """Future exchange market-data interface; no live connection."""


class TradingViewMarketDataProvider(MT5Provider):
    """Reserved interface only; TradingView is not scraped or used as canonical data."""


class PolygonProvider(MT5Provider):
    """Reserved read-only licensed-provider interface; no connection is implemented."""
