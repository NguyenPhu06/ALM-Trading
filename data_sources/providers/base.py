from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class ProviderHealth(StrEnum):
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
