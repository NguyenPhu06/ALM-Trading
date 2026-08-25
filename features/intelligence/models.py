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
    ohlcv: dict[str, Any] = field(default_factory=dict)
    candle_closed: bool | None = None
    internal_structure: str | None = None
    swing_structure: str | None = None
    equal_highs: tuple[float, ...] = field(default_factory=tuple)
    equal_lows: tuple[float, ...] = field(default_factory=tuple)
    premium_discount: str | None = None
    regime: str = "UNKNOWN"


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
    market_regime: dict[str, Any] = field(default_factory=dict)
    mtf_alignment: str = "INSUFFICIENT"
    confidence: float = 0.0
    data_quality: dict[str, Any] = field(default_factory=dict)
    signal: None = field(default=None)


# Stable public names requested by downstream dataset/backtest consumers.
MarketSnapshot = MarketStateSnapshot
MarketIntelligenceSnapshot = MarketStateSnapshot
