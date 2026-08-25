from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ProviderHealth(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_ERROR = "AUTH_ERROR"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    UNCONFIGURED = "UNCONFIGURED"


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    provider: str
    status: ProviderHealth
    last_success: datetime | None
    last_error: str | None
    latency: float | None
    supported_symbols: tuple[str, ...]
    supported_timeframes: tuple[str, ...]


class BaseMarketDataProvider(ABC):
    name: str
    supported_symbols: tuple[str, ...]
    supported_timeframes: tuple[str, ...]

    @abstractmethod
    def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def fetch_historical(
        self, symbol: str, timeframe: str, start: datetime, end: datetime,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def fetch_latest(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def fetch_incremental(
        self, symbol: str, timeframe: str, start: datetime, end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> ProviderStatus:
        raise NotImplementedError

    # Phase 7 canonical gateway names. Legacy adapters remain compatible.
    def get_latest_quote(self, symbol: str) -> dict[str, Any] | None:
        candle = self.fetch_latest(symbol, "M1")
        if candle is None:
            return None
        price = float(candle["close"])
        spread = float(candle.get("spread") or 0.0)
        return {"timestamp": candle["timestamp"], "symbol": symbol, "bid": price-spread/2,
                "ask": price+spread/2, "mid_price": price, "spread": spread,
                "spread_percent": spread/price if price else 0.0, "source": self.name}

    def get_candles(self, symbol: str, timeframe: str, *, limit: int = 500) -> list[dict[str, Any]]:
        from data_quality.validator import timeframe_delta
        end = datetime.now().astimezone()
        return self.fetch_historical(symbol, timeframe, end-timeframe_delta(timeframe)*limit, end)[-limit:]

    def get_historical_candles(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return self.fetch_historical(symbol, timeframe, start, end)

    def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        return {"symbol": symbol, "provider": self.name, "supported": symbol in self.supported_symbols}

    def get_market_status(self) -> dict[str, Any]:
        status = self.health_check()
        return {"provider": status.provider, "status": status.status.value, "timestamp": datetime.now().astimezone()}
