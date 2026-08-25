from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


STRATEGY_VERSION = "phase6.strategy.v1"
FEATURE_VERSION = "phase4.features.v1"


class SetupDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NONE = "NONE"


class SetupStatus(StrEnum):
    INVALID = "INVALID"
    WATCH = "WATCH"
    READY = "READY"
    EXECUTABLE_SIMULATION = "EXECUTABLE_SIMULATION"


@dataclass(frozen=True, slots=True)
class TimeframeStrategyState:
    timeframe: str
    timestamp: datetime | None
    trend: str
    structure: str | None
    swing_high: float | None
    swing_low: float | None
    bos: str | None
    choch: str | None
    volatility: str
    liquidity_context: dict[str, Any]
    indicators: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MultiTimeframeSnapshot:
    symbol: str
    timestamp: datetime
    timeframes: dict[str, TimeframeStrategyState]
    higher_timeframe_bias: str
    alignment: str
    conflicts: tuple[str, ...] = ()
    feature_version: str = FEATURE_VERSION


@dataclass(frozen=True, slots=True)
class StrategyScore:
    score: float
    components: dict[str, float]
    weighted_components: dict[str, float]
    reasons: tuple[str, ...]
    conflicts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StrategyConfidence:
    market_structure_confidence: float
    liquidity_confidence: float
    mtf_confidence: float
    indicator_confidence: float
    nn_confidence: float
    volatility_confidence: float
    final_confidence: float


@dataclass(frozen=True, slots=True)
class RiskDecision:
    risk_allowed: bool
    max_position_size: float
    max_dca_entries: int
    max_total_exposure: float
    max_drawdown_allowed: float
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TradeSetup:
    setup_id: str
    symbol: str
    timestamp: datetime
    direction: SetupDirection
    entry_price: float
    market_regime: str
    timeframe_alignment: str
    liquidity_context: dict[str, Any]
    structure_context: dict[str, Any]
    indicator_context: dict[str, Any]
    neural_prediction: dict[str, Any] | None
    risk_context: RiskDecision
    setup_score: StrategyScore
    confidence: StrategyConfidence
    status: SetupStatus
    reason_codes: tuple[str, ...]
    strategy_version: str = STRATEGY_VERSION
    feature_version: str = FEATURE_VERSION
    model_version: str | None = None


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    timestamp: datetime
    symbol: str
    decision: str
    setup: TradeSetup
    reason_codes: tuple[str, ...]
    strategy_version: str = STRATEGY_VERSION

