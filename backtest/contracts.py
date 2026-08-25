from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from features.intelligence import MarketStateSnapshot


class TradeDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class EvaluationAction(StrEnum):
    HOLD = "HOLD"
    EXIT = "EXIT"
    REDUCE = "REDUCE"
    INVALIDATE = "INVALIDATE"


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    action: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SimulationRiskLimits:
    maximum_exposure: float
    maximum_drawdown: float
    allow_counter_trend: bool = True

    def __post_init__(self) -> None:
        if self.maximum_exposure <= 0 or not 0 < self.maximum_drawdown < 1:
            raise ValueError("invalid simulation risk limits")


class SnapshotStrategy(ABC):
    """Backtest-only contract. It has no execution or broker dependency."""

    @abstractmethod
    def evaluate(self, snapshot: MarketStateSnapshot) -> StrategyDecision:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    entry_time: datetime
    entry_price: float
    exit_time: datetime | None
    exit_price: float | None
    direction: TradeDirection
    size: float
    pnl: float
    drawdown: float
    reason: str
    counter_trend_trade: bool
    entries: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    evaluations: tuple[dict[str, Any], ...] = field(default_factory=tuple)
