from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


CALCULATION_VERSION = "phase3.v1"


class MarketBias(StrEnum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


@dataclass(frozen=True, slots=True)
class TimeframeIntelligence:
    timestamp: datetime | None
    symbol: str
    timeframe: str
    available: bool
    trend: str
    structure: str | None
    bos: str | None
    choch: str | None
    swing_high: float | None
    swing_low: float | None
    liquidity: dict[str, Any]
    sweep: dict[str, Any] | None
    fvg: dict[str, Any] | None
    order_block: dict[str, Any] | None
    displacement: dict[str, Any] | None
    indicators: dict[str, Any]
    volatility: dict[str, Any]
    session: str | None
    session_range: float | None
    calculation_version: str = CALCULATION_VERSION


@dataclass(frozen=True, slots=True)
class ConfluenceScore:
    score: float
    components: dict[str, float]
    reasons: tuple[str, ...]
    conflicts: tuple[str, ...]
    calculation_version: str = CALCULATION_VERSION
    timestamp: datetime | None = None
    symbol: str | None = None
    timeframe: str = "MTF"


@dataclass(frozen=True, slots=True)
class FeatureVector:
    names: tuple[str, ...]
    values: tuple[float, ...]
    calculation_version: str = CALCULATION_VERSION
    timestamp: datetime | None = None
    symbol: str | None = None
    timeframe: str = "MTF"

    def as_dict(self) -> dict[str, float]:
        return dict(zip(self.names, self.values))


@dataclass(frozen=True, slots=True)
class MarketStateSnapshot:
    timestamp: datetime
    symbol: str
    timeframes: dict[str, TimeframeIntelligence]
    bias: MarketBias
    bias_score: float
    confluence: ConfluenceScore
    trade_state: str
    no_trade_reasons: tuple[str, ...]
    reasons: tuple[str, ...]
    conflicts: tuple[str, ...]
    feature_vector: FeatureVector
    calculation_version: str = CALCULATION_VERSION
    signal: None = field(default=None)
