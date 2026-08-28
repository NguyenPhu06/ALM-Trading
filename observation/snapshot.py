"""Feature and market snapshots for one observation cycle.

The feature snapshot is deliberately complete: it captures everything the cycle
saw and everything it concluded, so that it can serve as future training data
without needing the pipeline re-run. It is a record, not an instruction.
"""
from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass, asdict
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4


def jsonable(value: Any) -> Any:
    """Make a payload safe for a JSON column without losing structure."""
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    return value


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    """Everything one analysis cycle observed and concluded."""

    cycle_id: str
    symbol: str
    timestamp: datetime
    market_data: dict[str, Any] = field(default_factory=dict)
    timeframes: dict[str, Any] = field(default_factory=dict)
    structure: dict[str, Any] = field(default_factory=dict)
    liquidity: dict[str, Any] = field(default_factory=dict)
    indicators: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    regime: dict[str, Any] = field(default_factory=dict)
    spread: dict[str, Any] = field(default_factory=dict)
    volatility: dict[str, Any] = field(default_factory=dict)
    neural_network: dict[str, Any] | None = None
    strategy: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    data_quality: dict[str, Any] = field(default_factory=dict)
    execution_simulation: dict[str, Any] = field(default_factory=dict)
    dca_projection: dict[str, Any] | None = None
    time_exit: dict[str, Any] | None = None
    feature_version: str = "phase12.features.v1"
    source: str = "mt5"

    def as_dict(self) -> dict[str, Any]:
        return jsonable({
            "cycle_id": self.cycle_id, "symbol": self.symbol, "timestamp": self.timestamp,
            "market_data": self.market_data, "timeframes": self.timeframes,
            "structure": self.structure, "liquidity": self.liquidity,
            "indicators": self.indicators, "session": self.session, "regime": self.regime,
            "spread": self.spread, "volatility": self.volatility,
            "neural_network": self.neural_network, "strategy": self.strategy,
            "risk": self.risk, "data_quality": self.data_quality,
            "execution_simulation": self.execution_simulation,
            "dca_projection": self.dca_projection, "time_exit": self.time_exit,
            "feature_version": self.feature_version, "source": self.source,
        })


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """The /market/snapshot payload: one coherent view of the market right now."""

    symbol: str
    timestamp: datetime
    price: dict[str, Any] = field(default_factory=dict)
    spread: dict[str, Any] = field(default_factory=dict)
    session: dict[str, Any] = field(default_factory=dict)
    regime: dict[str, Any] = field(default_factory=dict)
    timeframes: dict[str, Any] = field(default_factory=dict)
    structure: dict[str, Any] = field(default_factory=dict)
    liquidity: dict[str, Any] = field(default_factory=dict)
    indicators: dict[str, Any] = field(default_factory=dict)
    neural_network: dict[str, Any] | None = None
    strategy: dict[str, Any] = field(default_factory=dict)
    risk: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    data_quality: dict[str, Any] = field(default_factory=dict)
    source: str = "mt5"
    cycle_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return jsonable({
            "symbol": self.symbol, "timestamp": self.timestamp, "price": self.price,
            "spread": self.spread, "sessions": self.session, "regime": self.regime,
            "timeframes": self.timeframes, "structure": self.structure,
            "liquidity": self.liquidity, "indicators": self.indicators,
            "neural_network": self.neural_network, "strategy": self.strategy,
            "risk": self.risk, "execution": self.execution,
            "data_quality": self.data_quality, "source": self.source,
            "cycle_id": self.cycle_id,
        })


def new_cycle_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
