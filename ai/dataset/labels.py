"""Forward-outcome labelling.

The single rule this module exists to enforce: **a label is only ever produced
after its horizon has fully elapsed**. `LabelingEngine.label` refuses to emit a
label when the supplied future window does not reach the horizon, so an
incomplete window yields nothing rather than a partial, look-ahead-contaminated
target.

Costs are subtracted before anything is called profitable. A gross move that does
not clear spread + slippage + commission + swap is UNPROFITABLE, not a small win.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Mapping, Sequence

from config.settings import load_yaml
from ai.dataset.versioning import LABEL_VERSION

# Human-readable horizon -> duration. Configurable via phase_13.horizons.
HORIZONS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5), "15m": timedelta(minutes=15), "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1), "2h": timedelta(hours=2), "4h": timedelta(hours=4),
    "8h": timedelta(hours=8), "24h": timedelta(hours=24),
}


class Direction(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    NEUTRAL = "NEUTRAL"


class Outcome(StrEnum):
    PROFITABLE = "PROFITABLE"
    UNPROFITABLE = "UNPROFITABLE"


class LabelRefusal(StrEnum):
    HORIZON_NOT_ELAPSED = "HORIZON_NOT_ELAPSED"
    NO_FUTURE_DATA = "NO_FUTURE_DATA"
    INVALID_ENTRY = "INVALID_ENTRY"
    UNKNOWN_HORIZON = "UNKNOWN_HORIZON"


@dataclass(frozen=True, slots=True)
class TradingCosts:
    spread: float = 0.0
    slippage: float = 0.00002
    commission: float = 0.0
    swap_per_day: float = 0.0

    def total(self, *, holding: timedelta | None = None) -> float:
        """Round-trip cost in price terms."""
        days = (holding.total_seconds() / 86400.0) if holding else 0.0
        return abs(self.spread) + abs(self.slippage) + abs(self.commission) + abs(
            self.swap_per_day) * days


@dataclass(frozen=True, slots=True)
class ForwardLabel:
    """Every target for one observation at one horizon."""

    horizon: str
    entry_price: float
    future_price: float
    # classification
    direction: Direction
    # binary, cost-aware
    outcome: Outcome
    # regression
    future_return: float
    future_mfe: float
    future_mae: float
    future_volatility: float
    future_max_return: float
    future_max_drawdown: float
    net_return: float
    costs: float
    # time-to-event, seconds; None when the event never occurred in the window
    time_to_profit: float | None = None
    time_to_stop: float | None = None
    time_to_max_adverse: float | None = None
    label_version: str = LABEL_VERSION
    resolved_at: datetime | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon, "entry_price": self.entry_price,
            "future_price": self.future_price, "direction": str(self.direction),
            "outcome": str(self.outcome), "future_return": self.future_return,
            "future_mfe": self.future_mfe, "future_mae": self.future_mae,
            "future_volatility": self.future_volatility,
            "future_max_return": self.future_max_return,
            "future_max_drawdown": self.future_max_drawdown,
            "net_return": self.net_return, "costs": self.costs,
            "time_to_profit": self.time_to_profit, "time_to_stop": self.time_to_stop,
            "time_to_max_adverse": self.time_to_max_adverse,
            "label_version": self.label_version, "resolved_at": self.resolved_at,
        }


@dataclass(frozen=True, slots=True)
class LabelResult:
    label: ForwardLabel | None
    refusal: LabelRefusal | None = None

    @property
    def ok(self) -> bool:
        return self.label is not None


def resolve_horizon(name: str) -> timedelta:
    key = str(name).strip().lower()
    if key not in HORIZONS:
        raise KeyError(name)
    return HORIZONS[key]


class LabelingEngine:
    """Produces every documented target, only once the horizon has elapsed."""

    VERSION = LABEL_VERSION

    def __init__(self, *, classification_threshold: float | None = None,
                 costs: TradingCosts | None = None, direction: str = "LONG"):
        config = load_yaml().get("phase_13", {})
        cost_config = config.get("costs", {})
        self.classification_threshold = float(
            classification_threshold if classification_threshold is not None
            else config.get("classification_threshold", 0.0005))
        self.costs = costs or TradingCosts(
            slippage=float(cost_config.get("slippage", 0.00002)),
            commission=float(cost_config.get("commission", 0.0)),
            swap_per_day=float(cost_config.get("swap_per_day", 0.0)))
        self.direction = str(direction).upper()

    def label(self, *, entry_price: float, entry_time: datetime,
              future: Sequence[Mapping[str, Any]], horizon: str,
              spread: float = 0.0, now: datetime | None = None) -> LabelResult:
        """Label one observation. `future` must reach entry_time + horizon.

        Passing a window that stops short is refused: a truncated window would
        silently produce an optimistic label.
        """
        try:
            window = resolve_horizon(horizon)
        except KeyError:
            return LabelResult(None, LabelRefusal.UNKNOWN_HORIZON)
        if entry_price is None or entry_price <= 0:
            return LabelResult(None, LabelRefusal.INVALID_ENTRY)

        deadline = entry_time + window
        if now is not None and now < deadline:
            return LabelResult(None, LabelRefusal.HORIZON_NOT_ELAPSED)

        rows = [row for row in future
                if row.get("timestamp") is not None
                and entry_time < row["timestamp"] <= deadline]
        if not rows:
            return LabelResult(None, LabelRefusal.NO_FUTURE_DATA)
        if max(row["timestamp"] for row in rows) < deadline:
            # The window does not actually reach the horizon.
            return LabelResult(None, LabelRefusal.HORIZON_NOT_ELAPSED)

        sign = 1.0 if self.direction in {"LONG", "BUY"} else -1.0
        closes = [float(row["close"]) for row in rows]
        highs = [float(row.get("high", row["close"])) for row in rows]
        lows = [float(row.get("low", row["close"])) for row in rows]

        future_price = closes[-1]
        future_return = sign * (future_price - entry_price) / entry_price

        best = max(highs) if sign > 0 else min(lows)
        worst = min(lows) if sign > 0 else max(highs)
        mfe = sign * (best - entry_price) / entry_price
        mae = sign * (worst - entry_price) / entry_price          # negative when adverse

        returns = [sign * (close - entry_price) / entry_price for close in closes]
        max_return = max(returns)
        max_drawdown = min(returns)
        volatility = _stdev(returns)

        holding = deadline - entry_time
        costs = self.costs.total(holding=holding) + abs(float(spread or 0.0))
        cost_return = costs / entry_price
        net_return = future_return - cost_return

        if future_return > self.classification_threshold:
            direction = Direction.UP
        elif future_return < -self.classification_threshold:
            direction = Direction.DOWN
        else:
            direction = Direction.NEUTRAL

        # Cost-aware: a gross move that does not clear costs is not profitable.
        outcome = Outcome.PROFITABLE if net_return > 0 else Outcome.UNPROFITABLE

        label = ForwardLabel(
            horizon=str(horizon), entry_price=float(entry_price), future_price=future_price,
            direction=direction, outcome=outcome, future_return=future_return,
            future_mfe=mfe, future_mae=mae, future_volatility=volatility,
            future_max_return=max_return, future_max_drawdown=max_drawdown,
            net_return=net_return, costs=cost_return,
            time_to_profit=self._time_to(rows, entry_time, entry_price, sign, cost_return, True),
            time_to_stop=self._time_to(rows, entry_time, entry_price, sign, cost_return, False),
            time_to_max_adverse=self._time_to_extreme(rows, entry_time, entry_price, sign),
            resolved_at=deadline,
            context={"bars": len(rows), "direction": self.direction},
        )
        return LabelResult(label)

    @staticmethod
    def _time_to(rows, entry_time, entry_price, sign, cost_return, favourable) -> float | None:
        """Seconds until net return first crosses +/- the cost barrier."""
        for row in rows:
            reference = float(row.get("high" if sign > 0 else "low", row["close"])) if favourable \
                else float(row.get("low" if sign > 0 else "high", row["close"]))
            move = sign * (reference - entry_price) / entry_price
            crossed = move - cost_return > 0 if favourable else move + cost_return < 0
            if crossed:
                return (row["timestamp"] - entry_time).total_seconds()
        return None

    @staticmethod
    def _time_to_extreme(rows, entry_time, entry_price, sign) -> float | None:
        worst_value = None
        worst_time = None
        for row in rows:
            reference = float(row.get("low" if sign > 0 else "high", row["close"]))
            move = sign * (reference - entry_price) / entry_price
            if worst_value is None or move < worst_value:
                worst_value, worst_time = move, row["timestamp"]
        return (worst_time - entry_time).total_seconds() if worst_time else None

    def label_many(self, *, entry_price: float, entry_time: datetime,
                   future: Sequence[Mapping[str, Any]], horizons: Sequence[str],
                   spread: float = 0.0, now: datetime | None = None) -> dict[str, LabelResult]:
        return {horizon: self.label(entry_price=entry_price, entry_time=entry_time,
                                    future=future, horizon=horizon, spread=spread, now=now)
                for horizon in horizons}


def _stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return variance ** 0.5
