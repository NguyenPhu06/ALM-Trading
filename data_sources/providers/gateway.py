from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from data_sources.normalizer import CandleNormalizer, normalize_symbol, normalize_timeframe
from data_sources.providers.base import BaseMarketDataProvider, ProviderHealth, ProviderStatus


class MockMarketDataProvider(BaseMarketDataProvider):
    """Deterministic test provider. Rows are supplied by tests, never generated."""
    name = "mock"
    supported_symbols = ("EURUSD",)
    supported_timeframes = ("M5", "M15", "M30", "H1", "H4", "D1")

    def __init__(self, rows: Sequence[dict[str, Any]], quote: dict[str, Any] | None = None):
        self.rows = list(rows); self.quote = quote; self.connected = False
    def connect(self): self.connected = True
    def disconnect(self): self.connected = False
    def fetch_historical(self, symbol, timeframe, start, end):
        symbol, timeframe = normalize_symbol(symbol), normalize_timeframe(timeframe)
        return [row for row in self.rows if row["symbol"] == symbol and row["timeframe"] == timeframe and start <= row["timestamp"] <= end]
    def fetch_latest(self, symbol, timeframe):
        rows = self.get_candles(symbol, timeframe, limit=1); return rows[-1] if rows else None
    def fetch_incremental(self, symbol, timeframe, start, end=None):
        return self.fetch_historical(symbol, timeframe, start, end or datetime.now(timezone.utc))
    def get_candles(self, symbol, timeframe, *, limit=500):
        rows = sorted((r for r in self.rows if r["symbol"] == normalize_symbol(symbol) and r["timeframe"] == normalize_timeframe(timeframe)), key=lambda r:r["timestamp"])
        return rows[-limit:]
    def get_latest_quote(self, symbol): return dict(self.quote) if self.quote else super().get_latest_quote(symbol)
    def health_check(self): return ProviderStatus(self.name, ProviderHealth.HEALTHY, datetime.now(timezone.utc), None, 0., self.supported_symbols, self.supported_timeframes)


class TradingViewAdapter(BaseMarketDataProvider):
    """Legal-access placeholder only. No scraping and no alleged order-flow data."""
    name = "tradingview"
    supported_symbols = ()
    supported_timeframes = ()
    def connect(self): raise RuntimeError("TradingView market-data API is not configured; scraping is prohibited")
    def disconnect(self): return None
    def fetch_historical(self, *args, **kwargs): raise RuntimeError("TradingView provider UNAVAILABLE")
    def fetch_latest(self, *args, **kwargs): raise RuntimeError("TradingView provider UNAVAILABLE")
    def fetch_incremental(self, *args, **kwargs): raise RuntimeError("TradingView provider UNAVAILABLE")
    def health_check(self): return ProviderStatus(self.name, ProviderHealth.UNCONFIGURED, None, "LEGAL_API_UNAVAILABLE", None, (), ())

