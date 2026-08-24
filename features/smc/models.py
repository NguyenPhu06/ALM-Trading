from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


CALCULATION_VERSION = "phase3.v1"


@dataclass(frozen=True, slots=True)
class FairValueGap:
    timestamp: datetime
    symbol: str
    timeframe: str
    direction: str
    upper_price: Decimal
    lower_price: Decimal
    size: Decimal
    filled: bool
    fill_percentage: float
    state: str
    calculation_version: str = CALCULATION_VERSION


@dataclass(frozen=True, slots=True)
class OrderBlock:
    timestamp: datetime
    source_timestamp: datetime
    symbol: str
    timeframe: str
    direction: str
    zone_high: Decimal
    zone_low: Decimal
    strength: float
    mitigated: bool
    block_type: str = "ORDER_BLOCK"
    calculation_version: str = CALCULATION_VERSION


@dataclass(frozen=True, slots=True)
class DisplacementFeature:
    timestamp: datetime
    symbol: str
    timeframe: str
    body_size: Decimal
    range: Decimal
    atr_ratio: float | None
    direction: str
    volume_ratio: float | None
    displaced: bool
    calculation_version: str = CALCULATION_VERSION


@dataclass(frozen=True, slots=True)
class RejectionFeature:
    timestamp: datetime
    symbol: str
    timeframe: str
    direction: str
    wick_ratio: float
    rejected: bool
    calculation_version: str = CALCULATION_VERSION
