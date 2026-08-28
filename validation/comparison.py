"""SHADOW vs DEMO (section 6).

The question this module answers is not "did we make money" but "where did the
difference come from". A strategy that was right and filled badly needs a
different response from one that was wrong, and only an attribution can tell
them apart.

Nine differences are measured and each is classified. `NONE` is a real verdict,
not a fallback: when shadow and DEMO agree within tolerance, saying so is the
useful answer.

Where a figure is unavailable the comparison says so rather than assuming zero.
A missing exit is not a flat exit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Sequence

from config.settings import load_yaml


class DifferenceKind(StrEnum):
    """Section 6, in the order the classifier considers them."""

    NONE = "NONE"
    SIGNAL_ERROR = "SIGNAL_ERROR"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    MARKET_MOVEMENT = "MARKET_MOVEMENT"
    SPREAD_ERROR = "SPREAD_ERROR"
    SLIPPAGE_ERROR = "SLIPPAGE_ERROR"
    COST_ERROR = "COST_ERROR"
    TIMING_ERROR = "TIMING_ERROR"


NOT_COMPARABLE = "NOT_COMPARABLE"


def _delta(actual: Any, expected: Any) -> float | None:
    if actual is None or expected is None:
        return None
    return float(actual) - float(expected)


@dataclass(frozen=True, slots=True)
class ShadowDemoComparison:
    shadow_signal_id: str
    demo_execution_request_id: str
    symbol: str
    signal_difference: bool
    entry_difference: float | None = None
    exit_difference: float | None = None
    slippage_difference: float | None = None
    cost_difference: float | None = None
    pnl_difference: float | None = None
    mae_difference: float | None = None
    mfe_difference: float | None = None
    time_difference: float | None = None
    kinds: tuple[DifferenceKind, ...] = ()
    shadow_net_pnl: float | None = None
    demo_net_pnl: float | None = None
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def matched(self) -> bool:
        return self.kinds == (DifferenceKind.NONE,)

    @property
    def primary(self) -> DifferenceKind:
        return self.kinds[0] if self.kinds else DifferenceKind.NONE

    def as_dict(self) -> dict[str, Any]:
        return {
            "shadow_signal_id": self.shadow_signal_id,
            "demo_execution_request_id": self.demo_execution_request_id,
            "symbol": self.symbol, "signal_difference": self.signal_difference,
            "entry_difference": self.entry_difference,
            "exit_difference": self.exit_difference,
            "slippage_difference": self.slippage_difference,
            "cost_difference": self.cost_difference,
            "pnl_difference": self.pnl_difference,
            "mae_difference": self.mae_difference,
            "mfe_difference": self.mfe_difference,
            "time_difference": self.time_difference,
            "kinds": [str(kind) for kind in self.kinds],
            "primary": str(self.primary), "matched": self.matched,
            "shadow_net_pnl": self.shadow_net_pnl, "demo_net_pnl": self.demo_net_pnl,
            "details": dict(self.details), "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class DemoOutcomeView:
    """Section 5. What the DEMO trade actually did, net of what it actually cost."""

    request_id: str
    symbol: str
    side: str
    actual_entry: float | None = None
    actual_exit: float | None = None
    actual_pnl: float | None = None
    actual_mfe: float | None = None
    actual_mae: float | None = None
    actual_duration: float | None = None
    actual_spread: float | None = None
    actual_slippage: float | None = None
    commission: float = 0.0
    swap: float = 0.0
    net_actual_pnl: float | None = None
    exit_reason: str | None = None

    @classmethod
    def from_journal(cls, entry: Any) -> "DemoOutcomeView":
        payload = entry.as_dict() if hasattr(entry, "as_dict") else dict(entry or {})
        result = payload.get("mt5_result") or {}
        opened, closed = getattr(entry, "opened_at", None), getattr(entry, "closed_at", None)
        duration = (closed - opened).total_seconds() if opened and closed else None
        gross = payload.get("gross_pnl")
        net = payload.get("pnl")
        commission = float(payload.get("commission") or 0.0)
        swap = float(payload.get("swap") or 0.0)
        if net is None and gross is not None:
            net = float(gross) + commission + swap
        return cls(
            request_id=str(payload.get("request_id")), symbol=str(payload.get("symbol") or ""),
            side=str(payload.get("direction") or ""),
            actual_entry=result.get("filled_price"),
            actual_exit=(payload.get("mt5_result") or {}).get("exit_price"),
            actual_pnl=gross if gross is not None else net,
            actual_mfe=payload.get("mfe"), actual_mae=payload.get("mae"),
            actual_duration=duration,
            actual_spread=(payload.get("market_snapshot") or {}).get("spread"),
            actual_slippage=payload.get("slippage"),
            commission=commission, swap=swap, net_actual_pnl=net,
            exit_reason=payload.get("exit_reason"))

    @property
    def total_cost(self) -> float:
        return abs(self.commission) + abs(self.swap) + abs(self.actual_slippage or 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "symbol": self.symbol, "side": self.side,
            "actual_entry": self.actual_entry, "actual_exit": self.actual_exit,
            "actual_pnl": self.actual_pnl, "actual_mfe": self.actual_mfe,
            "actual_mae": self.actual_mae, "actual_duration": self.actual_duration,
            "actual_spread": self.actual_spread, "actual_slippage": self.actual_slippage,
            "commission": self.commission, "swap": self.swap,
            "net_actual_pnl": self.net_actual_pnl, "total_cost": self.total_cost,
            "exit_reason": self.exit_reason,
        }


class ShadowDemoComparator:
    """Compares one shadow signal with its DEMO twin and attributes the gap."""

    def __init__(self, *, entry_tolerance: float | None = None,
                 exit_tolerance: float | None = None, slippage_tolerance: float | None = None,
                 spread_tolerance: float | None = None, cost_tolerance: float | None = None,
                 time_tolerance_seconds: float | None = None):
        config = load_yaml().get("phase_17", {}).get("comparison", {})
        self.entry_tolerance = float(
            entry_tolerance if entry_tolerance is not None
            else config.get("entry_tolerance", 0.0002))
        self.exit_tolerance = float(
            exit_tolerance if exit_tolerance is not None else config.get("exit_tolerance", 0.0002))
        self.slippage_tolerance = float(
            slippage_tolerance if slippage_tolerance is not None
            else config.get("slippage_tolerance", 0.0003))
        self.spread_tolerance = float(
            spread_tolerance if spread_tolerance is not None
            else config.get("spread_tolerance", 0.0002))
        self.cost_tolerance = float(
            cost_tolerance if cost_tolerance is not None else config.get("cost_tolerance", 0.5))
        self.time_tolerance = float(
            time_tolerance_seconds if time_tolerance_seconds is not None
            else config.get("time_tolerance_seconds", 60.0))

    def compare(self, signal: Any, shadow: Any, demo: DemoOutcomeView) -> ShadowDemoComparison:
        """Nine differences, then the attribution.

        `signal` is the shadow signal, `shadow` its outcome, `demo` the executed
        result. A shadow signal whose DEMO twin never executed is not compared
        here — there is nothing to compare it with, and `compare_unexecuted`
        records that fact instead.
        """
        entry_difference = _delta(demo.actual_entry, shadow.expected_entry)
        exit_difference = _delta(demo.actual_exit, shadow.expected_exit)
        slippage_difference = _delta(abs(demo.actual_slippage) if demo.actual_slippage is not None
                                     else None, abs(shadow.slippage_estimate))
        shadow_cost = abs(shadow.spread) + abs(shadow.slippage_estimate) + abs(
            shadow.commission_estimate)
        cost_difference = _delta(demo.total_cost, shadow_cost)
        pnl_difference = _delta(demo.net_actual_pnl, shadow.net_expected_pnl)
        mae_difference = _delta(demo.actual_mae, shadow.mae)
        mfe_difference = _delta(demo.actual_mfe, shadow.mfe)
        time_difference = _delta(demo.actual_duration, shadow.duration_seconds)
        spread_difference = _delta(demo.actual_spread, shadow.spread)

        signal_difference = str(signal.side).upper() != str(demo.side).upper()

        kinds = self._classify(
            signal_difference=signal_difference, entry_difference=entry_difference,
            exit_difference=exit_difference, slippage_difference=slippage_difference,
            spread_difference=spread_difference, cost_difference=cost_difference,
            time_difference=time_difference, pnl_difference=pnl_difference)

        return ShadowDemoComparison(
            shadow_signal_id=signal.shadow_signal_id,
            demo_execution_request_id=signal.demo_execution_request_id,
            symbol=signal.symbol, signal_difference=signal_difference,
            entry_difference=entry_difference, exit_difference=exit_difference,
            slippage_difference=slippage_difference, cost_difference=cost_difference,
            pnl_difference=pnl_difference, mae_difference=mae_difference,
            mfe_difference=mfe_difference, time_difference=time_difference,
            kinds=kinds, shadow_net_pnl=shadow.net_expected_pnl,
            demo_net_pnl=demo.net_actual_pnl,
            details={"spread_difference": spread_difference,
                     "shadow_cost": round(shadow_cost, 8),
                     "demo_cost": round(demo.total_cost, 8),
                     "exit_reason": demo.exit_reason})

    def compare_unexecuted(self, signal: Any) -> ShadowDemoComparison:
        """A shadow signal DEMO never took. Recorded, never silently dropped.

        These are the most interesting rows in the table: they are the population
        the gates removed, and whether removing them helped is a question the
        performance gates can only answer if the rows exist.
        """
        return ShadowDemoComparison(
            shadow_signal_id=signal.shadow_signal_id,
            demo_execution_request_id=signal.demo_execution_request_id,
            symbol=signal.symbol, signal_difference=True,
            kinds=(DifferenceKind.SIGNAL_ERROR,),
            details={"reason": NOT_COMPARABLE,
                     "not_executed_reason": signal.not_executed_reason,
                     "blocked_reasons": list(signal.blocked_reasons)})

    def _classify(self, *, signal_difference: bool, entry_difference: float | None,
                  exit_difference: float | None, slippage_difference: float | None,
                  spread_difference: float | None, cost_difference: float | None,
                  time_difference: float | None,
                  pnl_difference: float | None) -> tuple[DifferenceKind, ...]:
        kinds: list[DifferenceKind] = []
        if signal_difference:
            # A different side is not an execution problem; it is a different trade.
            kinds.append(DifferenceKind.SIGNAL_ERROR)
        if entry_difference is not None and abs(entry_difference) > self.entry_tolerance:
            kinds.append(DifferenceKind.EXECUTION_ERROR)
        if exit_difference is not None and abs(exit_difference) > self.exit_tolerance:
            # The exit moving is the market, not the broker: the same exit rule
            # fired at a different price because price went somewhere else.
            kinds.append(DifferenceKind.MARKET_MOVEMENT)
        if spread_difference is not None and abs(spread_difference) > self.spread_tolerance:
            kinds.append(DifferenceKind.SPREAD_ERROR)
        if slippage_difference is not None and abs(slippage_difference) > self.slippage_tolerance:
            kinds.append(DifferenceKind.SLIPPAGE_ERROR)
        if cost_difference is not None and abs(cost_difference) > self.cost_tolerance:
            kinds.append(DifferenceKind.COST_ERROR)
        if time_difference is not None and abs(time_difference) > self.time_tolerance:
            kinds.append(DifferenceKind.TIMING_ERROR)
        if not kinds:
            # Everything inside tolerance. NONE is an answer, not an absence.
            return (DifferenceKind.NONE,)
        return tuple(dict.fromkeys(kinds))

    @staticmethod
    def summarize(comparisons: Sequence[ShadowDemoComparison], *,
                  minimum_samples: int = 30) -> dict[str, Any]:
        rows = [row for row in comparisons if row is not None]
        if not rows:
            return {"samples": 0, "reliable": False, "reasons": ["NO_COMPARISONS"],
                    "kinds": {}, "matched": 0}
        kinds: dict[str, int] = {}
        for row in rows:
            for kind in row.kinds:
                kinds[str(kind)] = kinds.get(str(kind), 0) + 1
        pnls = [row.pnl_difference for row in rows if row.pnl_difference is not None]
        entries = [row.entry_difference for row in rows if row.entry_difference is not None]
        slips = [row.slippage_difference for row in rows
                 if row.slippage_difference is not None]
        return {
            "samples": len(rows), "matched": sum(row.matched for row in rows),
            "kinds": dict(sorted(kinds.items())),
            "mean_pnl_difference": round(sum(pnls) / len(pnls), 8) if pnls else None,
            "worst_pnl_difference": round(min(pnls), 8) if pnls else None,
            "mean_entry_difference": round(sum(entries) / len(entries), 8) if entries else None,
            "mean_slippage_difference": round(sum(slips) / len(slips), 8) if slips else None,
            # A handful of paired trades is an anecdote, not a measurement.
            "reliable": len(rows) >= minimum_samples,
            "reasons": [] if len(rows) >= minimum_samples else ["INSUFFICIENT_SAMPLES"],
        }
