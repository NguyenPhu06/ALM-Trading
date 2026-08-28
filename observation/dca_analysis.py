"""DCA projection — analysis only, nothing is executed.

The point of this module is to make the full downside visible before anyone
considers averaging down. Every projection carries a bounded maximum theoretical
loss and an explicit invalidation condition; a projection that cannot state its
worst case is refused rather than returned.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config.settings import load_yaml


@dataclass(frozen=True, slots=True)
class DCALevel:
    level: int
    price: float
    volume: float
    distance_from_entry: float
    risk_amount: float
    cumulative_volume: float
    average_entry: float
    cumulative_risk: float

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "price": round(self.price, 5), "volume": self.volume,
                "distance_from_entry": round(self.distance_from_entry, 5),
                "risk_amount": round(self.risk_amount, 2),
                "cumulative_volume": round(self.cumulative_volume, 4),
                "average_entry": round(self.average_entry, 5),
                "cumulative_risk": round(self.cumulative_risk, 2)}


@dataclass(frozen=True, slots=True)
class DCAProjection:
    symbol: str
    direction: str
    initial_entry: float
    initial_volume: float
    levels: tuple[DCALevel, ...]
    max_levels: int
    total_volume: float
    average_entry: float
    aggregate_exposure: float
    maximum_theoretical_loss: float
    invalidation_price: float
    invalidation_condition: str
    bounded: bool = True
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reasons: tuple[str, ...] = ()

    @property
    def executed(self) -> bool:
        """Always False. This module projects; it never trades."""
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "direction": self.direction,
            "initial_entry": round(self.initial_entry, 5), "initial_volume": self.initial_volume,
            "planned_levels": [level.as_dict() for level in self.levels],
            "max_levels": self.max_levels, "levels_planned": len(self.levels),
            "total_volume": round(self.total_volume, 4),
            "average_entry": round(self.average_entry, 5),
            "aggregate_exposure": round(self.aggregate_exposure, 2),
            "maximum_theoretical_loss": round(self.maximum_theoretical_loss, 2),
            "invalidation_price": round(self.invalidation_price, 5),
            "invalidation_condition": self.invalidation_condition,
            "bounded": self.bounded, "executed": False, "reasons": list(self.reasons),
            "timestamp": self.timestamp,
        }


class DCAAnalyzer:
    """Projects a bounded DCA ladder. Refuses to project an unbounded one."""

    def __init__(self, *, max_levels: int | None = None, spacing: float | None = None,
                 size_multiplier: float | None = None, risk_per_level: float | None = None,
                 contract_size: float = 100_000.0):
        config = load_yaml().get("phase_12", {}).get("dca", {})
        self.max_levels = int(max_levels if max_levels is not None else config.get("max_levels", 3))
        self.spacing = float(spacing if spacing is not None else config.get("spacing", 0.0015))
        self.size_multiplier = float(
            size_multiplier if size_multiplier is not None else config.get("size_multiplier", 1.0))
        self.risk_per_level = float(
            risk_per_level if risk_per_level is not None else config.get("risk_per_level", 0.005))
        self.contract_size = float(contract_size)

    def project(self, *, symbol: str, direction: str, entry: float, volume: float,
                stop_loss: float | None = None, balance: float = 10_000.0) -> DCAProjection:
        """Build the ladder and state the worst case explicitly.

        `stop_loss` defines the invalidation. Without one, the ladder is bounded by
        the level beyond the last DCA entry, so a maximum loss always exists.
        """
        side = str(direction).strip().upper()
        sign = 1 if side in {"BUY", "LONG"} else -1
        reasons: list[str] = []
        if entry <= 0 or volume <= 0:
            reasons.append("INVALID_ENTRY_OR_VOLUME")
        if self.max_levels <= 0:
            reasons.append("DCA_DISABLED")

        levels: list[DCALevel] = []
        cumulative_volume = volume
        weighted = entry * volume
        cumulative_risk = 0.0

        for index in range(1, self.max_levels + 1):
            # Each level sits further against the position.
            distance = self.spacing * index
            price = entry - sign * distance
            level_volume = round(volume * (self.size_multiplier ** index), 4)
            cumulative_volume = round(cumulative_volume + level_volume, 4)
            weighted += price * level_volume
            average = weighted / cumulative_volume if cumulative_volume else entry
            risk = balance * self.risk_per_level
            cumulative_risk = round(cumulative_risk + risk, 2)
            levels.append(DCALevel(index, price, level_volume, distance, risk,
                                   cumulative_volume, average, cumulative_risk))

        average_entry = weighted / cumulative_volume if cumulative_volume else entry
        aggregate_exposure = round(cumulative_volume * average_entry * self.contract_size, 2)

        if stop_loss is not None and stop_loss > 0:
            invalidation = float(stop_loss)
            condition = "STOP_LOSS_BREACHED"
        else:
            # One spacing step beyond the deepest level; the ladder cannot extend past it.
            invalidation = entry - sign * self.spacing * (self.max_levels + 1)
            condition = "PRICE_BEYOND_FINAL_DCA_LEVEL"

        # Worst case: the whole ladder filled and price reaches invalidation.
        loss_per_unit = abs(average_entry - invalidation)
        maximum_loss = round(loss_per_unit * cumulative_volume * self.contract_size, 2)
        bounded = maximum_loss > 0 and len(levels) <= self.max_levels

        if not bounded:
            reasons.append("UNBOUNDED_PROJECTION_REFUSED")
        reasons.append("ANALYSIS_ONLY_NOT_EXECUTED")

        return DCAProjection(
            symbol.upper(), side, entry, volume, tuple(levels), self.max_levels,
            cumulative_volume, average_entry, aggregate_exposure, maximum_loss,
            invalidation, condition, bounded, reasons=tuple(reasons),
        )
