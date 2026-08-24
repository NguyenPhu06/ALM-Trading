from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any


class TimestampedDataSource(ABC):
    """Read-only contract for future licensed/public source adapters."""

    @abstractmethod
    def fetch(self, *, symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        raise NotImplementedError


class FuturesDataProvider(TimestampedDataSource):
    pass


class NewsProvider(TimestampedDataSource):
    pass


class OpenInterestProvider(TimestampedDataSource):
    pass


class VolumeProvider(TimestampedDataSource):
    pass


class OrderBookProvider(TimestampedDataSource):
    pass


# These are interface declarations only. No network connection, credentials,
# broker execution, or synthetic observations are implemented in Phase 1A.

