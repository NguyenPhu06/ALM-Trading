"""Forward outcome, computed only after the horizon has elapsed (sections 6, 7).

The engine answers one question: given what the system predicted at time T, what
actually happened by T + horizon? It refuses to answer early. A truncated future
window produces a refusal, not an optimistic number.

Every figure is reported gross **and** net. `net_hypothetical_pnl` is the primary
performance metric — a gross win that does not clear spread, commission, slippage
and swap is not a win.

Nothing here is a fill. These are hypothetical outcomes of observations the
system recorded but never executed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Mapping, Sequence

from ai.dataset.labels import LabelingEngine, LabelResult, TradingCosts, resolve_horizon
from ai.edge.evidence import EvidenceSource
from config.settings import load_yaml
from observation.snapshot import jsonable


class OutcomeRefusal(StrEnum):
    HORIZON_NOT_REACHED = "HORIZON_NOT_REACHED"
    NO_FUTURE_DATA = "NO_FUTURE_DATA"
    NO_ENTRY_PRICE = "NO_ENTRY_PRICE"
    UNKNOWN_HORIZON = "UNKNOWN_HORIZON"
    NOT_DIRECTIONAL = "NOT_DIRECTIONAL"


DIRECTIONAL = {"BUY": 1.0, "LONG": 1.0, "SELL": -1.0, "SHORT": -1.0}


@dataclass(frozen=True, slots=True)
class ExecutionCosts:
    """Section 7. Every component that stands between a move and a profit."""

    spread: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0
    swap: float = 0.0

    @property
    def total(self) -> float:
        return abs(self.spread) + abs(self.commission) + abs(self.slippage) + abs(self.swap)

    def as_dict(self) -> dict[str, Any]:
        return {"spread": self.spread, "commission": self.commission,
                "slippage": self.slippage, "swap": self.swap, "total": self.total}


@dataclass(frozen=True, slots=True)
class ForwardOutcome:
    observation_id: str
    symbol: str
    horizon: str
    direction: str
    entry_price: float
    future_price: float
    future_return: float
    mfe: float
    mae: float
    maximum_favorable_excursion: float
    maximum_adverse_excursion: float
    hypothetical_pnl: float
    holding_time: float
    spread: float
    estimated_cost: float
    net_hypothetical_pnl: float
    resolved_at: datetime
    label: Any = None
    bars: int = 0
    evidence: EvidenceSource = EvidenceSource.FORWARD_OBSERVATION
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def profitable(self) -> bool:
        """Net, never gross."""
        return self.net_hypothetical_pnl > 0

    @property
    def actual_direction(self) -> str:
        """What the market did — not what the observation earned.

        `future_return` is signed by the observed direction, so a profitable SELL
        carries a positive return while the market fell. Deriving the direction
        from the return would therefore call every winning SELL an "UP" market
        and mark it as a wrong prediction. Use the raw price move instead.
        """
        move = self.future_price - self.entry_price
        if move > 0:
            return "UP"
        if move < 0:
            return "DOWN"
        return "NEUTRAL"

    @property
    def predicted_direction(self) -> str:
        return {"BUY": "UP", "LONG": "UP", "SELL": "DOWN",
                "SHORT": "DOWN"}.get(self.direction.upper(), "NEUTRAL")

    def as_dict(self) -> dict[str, Any]:
        return jsonable({
            "observation_id": self.observation_id, "symbol": self.symbol,
            "horizon": self.horizon, "direction": self.direction,
            "entry_price": self.entry_price, "future_price": self.future_price,
            "future_return": self.future_return, "mfe": self.mfe, "mae": self.mae,
            "maximum_favorable_excursion": self.maximum_favorable_excursion,
            "maximum_adverse_excursion": self.maximum_adverse_excursion,
            "hypothetical_pnl": self.hypothetical_pnl, "holding_time": self.holding_time,
            "spread": self.spread, "estimated_cost": self.estimated_cost,
            "net_hypothetical_pnl": self.net_hypothetical_pnl,
            "resolved_at": self.resolved_at, "bars": self.bars,
            "profitable": self.profitable, "actual_direction": self.actual_direction,
            "predicted_direction": self.predicted_direction,
            "evidence": str(self.evidence),
            "label": self.label.as_dict() if self.label is not None else None,
            "context": self.context,
        })


@dataclass(frozen=True, slots=True)
class OutcomeResult:
    outcome: ForwardOutcome | None
    refusal: OutcomeRefusal | None = None
    label_refusal: Any = None

    @property
    def ok(self) -> bool:
        return self.outcome is not None


class ForwardOutcomeEngine:
    """Resolves an observation once, after its horizon has elapsed."""

    def __init__(self, *, costs: ExecutionCosts | None = None,
                 labeler: LabelingEngine | None = None):
        config = load_yaml().get("phase_13", {}).get("costs", {})
        self.default_costs = costs or ExecutionCosts(
            commission=float(config.get("commission", 0.0)),
            slippage=float(config.get("slippage", 0.00002)),
            swap=0.0)
        self.swap_per_day = float(config.get("swap_per_day", 0.0))
        self.labeler = labeler

    # ------------------------------------------------------------------ costs
    def costs_for(self, *, spread: float | None, holding: timedelta) -> ExecutionCosts:
        days = max(holding.total_seconds(), 0.0) / 86400.0
        return ExecutionCosts(
            spread=abs(float(spread or 0.0)),
            commission=self.default_costs.commission,
            slippage=self.default_costs.slippage,
            swap=abs(self.swap_per_day) * days)

    # ---------------------------------------------------------------- resolve
    def resolve(self, observation: Any, candles: Sequence[Mapping[str, Any]], *,
                now: datetime) -> OutcomeResult:
        """Compute the outcome, or refuse with a reason.

        `now` is mandatory: without it the engine cannot know whether the horizon
        has elapsed, and an outcome computed early is look-ahead by construction.
        """
        direction = str(getattr(observation, "direction", "") or "").upper()
        sign = DIRECTIONAL.get(direction)
        if sign is None:
            return OutcomeResult(None, OutcomeRefusal.NOT_DIRECTIONAL)

        entry = getattr(observation, "entry_price", None)
        if entry is None or float(entry) <= 0:
            return OutcomeResult(None, OutcomeRefusal.NO_ENTRY_PRICE)
        entry = float(entry)

        horizon = str(getattr(observation, "observation_horizon", "1h"))
        try:
            window = resolve_horizon(horizon)
        except KeyError:
            return OutcomeResult(None, OutcomeRefusal.UNKNOWN_HORIZON)

        entry_time = observation.timestamp
        deadline = entry_time + window
        if now < deadline:
            return OutcomeResult(None, OutcomeRefusal.HORIZON_NOT_REACHED)

        rows = sorted((row for row in candles
                       if row.get("timestamp") is not None
                       and entry_time < row["timestamp"] <= deadline),
                      key=lambda row: row["timestamp"])
        if not rows:
            return OutcomeResult(None, OutcomeRefusal.NO_FUTURE_DATA)
        if max(row["timestamp"] for row in rows) < deadline:
            # The window stops short of the horizon; resolving now would be early.
            return OutcomeResult(None, OutcomeRefusal.HORIZON_NOT_REACHED)

        spread = float((getattr(observation, "context", {}) or {}).get("spread") or 0.0)
        holding = deadline - entry_time
        costs = self.costs_for(spread=spread, holding=holding)

        closes = [float(row["close"]) for row in rows]
        highs = [float(row.get("high", row["close"])) for row in rows]
        lows = [float(row.get("low", row["close"])) for row in rows]

        future_price = closes[-1]
        # Signed by the observed direction: a SELL that falls is a positive return.
        future_return = sign * (future_price - entry) / entry
        best = max(highs) if sign > 0 else min(lows)
        worst = min(lows) if sign > 0 else max(highs)
        mfe = sign * (best - entry) / entry
        mae = sign * (worst - entry) / entry

        cost_return = costs.total / entry
        net = future_return - cost_return

        label = None
        label_refusal = None
        if self.labeler is not None:
            result: LabelResult = self.labeler.label(
                entry_price=entry, entry_time=entry_time, future=rows, horizon=horizon,
                spread=spread, now=now)
            label, label_refusal = result.label, result.refusal

        outcome = ForwardOutcome(
            observation_id=getattr(observation, "observation_id", ""),
            symbol=str(getattr(observation, "symbol", "")).upper(), horizon=horizon,
            direction=direction, entry_price=entry, future_price=future_price,
            future_return=future_return, mfe=mfe, mae=mae,
            maximum_favorable_excursion=mfe, maximum_adverse_excursion=mae,
            hypothetical_pnl=future_return, holding_time=holding.total_seconds(),
            spread=spread, estimated_cost=cost_return, net_hypothetical_pnl=net,
            resolved_at=deadline, label=label, bars=len(rows),
            context={"costs": costs.as_dict(), "sign": sign,
                     "predicted_direction": direction})
        return OutcomeResult(outcome, None, label_refusal)


def costs_from_settings(spread: float | None = None) -> ExecutionCosts:
    """Convenience for callers that only need the configured cost profile."""
    return ForwardOutcomeEngine().costs_for(spread=spread, holding=timedelta())
