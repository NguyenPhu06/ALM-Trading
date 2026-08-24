from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from features.regime import MarketRegimeSnapshot


class RegimeDrivenStrategy(ABC):
    """Strategy boundary: regime decisions receive no raw candle collection."""

    @abstractmethod
    def evaluate(self, snapshot: MarketRegimeSnapshot) -> Any:
        raise NotImplementedError
