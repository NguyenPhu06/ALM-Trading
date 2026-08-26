"""Read-only MT5 market-data provider.

Implements the standard `BaseMarketDataProvider` contract so MT5 candles flow
through the existing ingestion, quality, snapshot, feature, intelligence and
strategy path with no strategy code aware of MetaTrader 5.

It has NO execution methods. `BaseMarketDataProvider` has none either, so nothing
in this class can place, modify or close an order.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from data_sources.providers.base import BaseMarketDataProvider, ProviderHealth, ProviderStatus

logger = logging.getLogger(__name__)


class MT5MarketDataProvider(BaseMarketDataProvider):
    """Adapts `MT5ReadOnlyClient` onto the ALM provider interface."""

    name = "mt5"
    supported_timeframes = ("D1", "H4", "H1", "M30", "M15", "M5")

    def __init__(self, client: Any | None = None, *, symbols: tuple[str, ...] = ()):
        if client is None:
            from execution.mt5.client import MT5ReadOnlyClient

            client = MT5ReadOnlyClient()
        self.client = client
        self.supported_symbols = tuple(symbols) or tuple(getattr(client, "canonical_symbols", ()))
        self._last_success: datetime | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------ lifecycle
    def connect(self) -> None:
        report = self.client.connect()
        state = str(getattr(report, "state", ""))
        if state == "CONNECTED":
            self._last_success = datetime.now(timezone.utc)
            self._last_error = None
        else:
            self._last_error = getattr(report, "code", state)

    def disconnect(self) -> None:
        self.client.disconnect()

    # --------------------------------------------------------------- market data
    def _rates(self, symbol: str, timeframe: str, count: int) -> list[dict[str, Any]]:
        result = self.client.get_rates(symbol, timeframe, count)
        if not result.ok:
            self._last_error = result.code
            logger.info("MT5 rates unavailable for %s %s: %s", symbol, timeframe, result.code)
            return []
        self._last_success = datetime.now(timezone.utc)
        self._last_error = None
        return list(result.data)

    def fetch_historical(self, symbol: str, timeframe: str, start: datetime,
                         end: datetime) -> list[dict[str, Any]]:
        """MT5 serves a bounded recent window; the range is applied after the read."""
        candles = self._rates(symbol, timeframe, int(getattr(self.client, "default_count", 500)))
        return [candle for candle in candles if start <= candle["timestamp"] <= end]

    def fetch_latest(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        candles = self._rates(symbol, timeframe, 2)
        return candles[-1] if candles else None

    def fetch_incremental(self, symbol: str, timeframe: str, start: datetime,
                          end: datetime | None = None) -> list[dict[str, Any]]:
        finish = end or datetime.now(timezone.utc)
        return self.fetch_historical(symbol, timeframe, start, finish)

    def get_latest_quote(self, symbol: str) -> dict[str, Any] | None:
        """Real bid/ask from the terminal rather than a candle-derived estimate."""
        result = self.client.get_tick(symbol)
        if not result.ok:
            self._last_error = result.code
            return None
        self._last_success = datetime.now(timezone.utc)
        return dict(result.data)

    def get_candles(self, symbol: str, timeframe: str, *, limit: int = 500) -> list[dict[str, Any]]:
        return self._rates(symbol, timeframe, limit)[-limit:]

    def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        result = self.client.get_symbol_info(symbol)
        if not result.ok:
            return {"symbol": symbol, "provider": self.name, "supported": False, "code": result.code}
        return {**result.data, "provider": self.name, "supported": True}

    # -------------------------------------------------------------------- health
    def health_check(self) -> ProviderStatus:
        report = self.client.health_check()
        mapping = {
            "ONLINE": ProviderHealth.ONLINE, "DEGRADED": ProviderHealth.DEGRADED,
            "STALE": ProviderHealth.DEGRADED, "OFFLINE": ProviderHealth.OFFLINE,
            "ERROR": ProviderHealth.ERROR,
        }
        return ProviderStatus(
            self.name, mapping.get(str(report.state), ProviderHealth.OFFLINE),
            self._last_success, self._last_error, None,
            self.supported_symbols, self.supported_timeframes,
        )
