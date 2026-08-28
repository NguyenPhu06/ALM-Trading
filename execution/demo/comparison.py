"""Paper vs DEMO, and DEMO vs OBSERVATION (sections 29 and 32).

Section 29 measures execution reality against model assumptions: the paper engine
predicted an entry, an exit and a cost; the broker produced its own. The gap is
the part of the edge that the simulation was quietly giving away.

Section 32 goes one step further back. An observation expected a result, paper
produced one, and DEMO produced another. Attributing the difference to signal,
execution, spread, slippage, model, strategy or a risk rejection is the whole
point: "the strategy lost money" and "the strategy was right and the fill was
bad" call for opposite responses.

Nothing here adjusts a number to make the comparison look better. Where a figure
is unavailable the attribution says so instead of assuming zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from config.settings import load_yaml

# Error attribution vocabulary (section 32).
SIGNAL_QUALITY_ERROR = "SIGNAL_QUALITY_ERROR"
EXECUTION_ERROR = "EXECUTION_ERROR"
SPREAD_ERROR = "SPREAD_ERROR"
SLIPPAGE_ERROR = "SLIPPAGE_ERROR"
MODEL_ERROR = "MODEL_ERROR"
STRATEGY_ERROR = "STRATEGY_ERROR"
RISK_REJECTION = "RISK_REJECTION"
NOT_COMPARABLE = "NOT_COMPARABLE"


def _delta(actual: Any, expected: Any) -> float | None:
    if actual is None or expected is None:
        return None
    return float(actual) - float(expected)


@dataclass(frozen=True, slots=True)
class PaperDemoComparison:
    request_id: str
    symbol: str
    paper_entry: float | None = None
    demo_entry: float | None = None
    paper_exit: float | None = None
    demo_exit: float | None = None
    entry_difference: float | None = None
    exit_difference: float | None = None
    spread: float | None = None
    slippage: float | None = None
    commission: float | None = None
    swap: float | None = None
    paper_net_pnl: float | None = None
    demo_net_pnl: float | None = None
    pnl_difference: float | None = None
    within_tolerance: bool = False
    reasons: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "symbol": self.symbol,
                "paper_entry": self.paper_entry, "demo_entry": self.demo_entry,
                "paper_exit": self.paper_exit, "demo_exit": self.demo_exit,
                "entry_difference": self.entry_difference,
                "exit_difference": self.exit_difference,
                "spread": self.spread, "slippage": self.slippage,
                "commission": self.commission, "swap": self.swap,
                "paper_net_pnl": self.paper_net_pnl, "demo_net_pnl": self.demo_net_pnl,
                "pnl_difference": self.pnl_difference,
                "within_tolerance": self.within_tolerance,
                "reasons": list(self.reasons), "timestamp": self.timestamp}


@dataclass(frozen=True, slots=True)
class ExecutionAttribution:
    request_id: str
    symbol: str
    observation_expected: float | None = None
    paper_result: float | None = None
    demo_result: float | None = None
    observation_gap: float | None = None
    paper_gap: float | None = None
    errors: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "symbol": self.symbol,
                "observation_expected": self.observation_expected,
                "paper_result": self.paper_result, "demo_result": self.demo_result,
                "observation_gap": self.observation_gap, "paper_gap": self.paper_gap,
                "errors": list(self.errors), "details": dict(self.details),
                "timestamp": self.timestamp}


class ExecutionComparator:
    """Compares what was expected with what a broker actually did."""

    def __init__(self, *, entry_tolerance: float | None = None,
                 exit_tolerance: float | None = None, slippage_tolerance: float | None = None):
        config = load_yaml().get("phase_16", {}).get("comparison", {})
        self.entry_tolerance = float(
            entry_tolerance if entry_tolerance is not None else config.get("entry_tolerance", 0.0002))
        self.exit_tolerance = float(
            exit_tolerance if exit_tolerance is not None else config.get("exit_tolerance", 0.0002))
        self.slippage_tolerance = float(
            slippage_tolerance if slippage_tolerance is not None
            else config.get("slippage_tolerance", 0.0003))

    # ------------------------------------------------------------ section 29
    def compare(self, *, request_id: str, symbol: str, paper_entry: float | None = None,
                demo_entry: float | None = None, paper_exit: float | None = None,
                demo_exit: float | None = None, spread: float | None = None,
                slippage: float | None = None, commission: float | None = None,
                swap: float | None = None, paper_net_pnl: float | None = None,
                demo_net_pnl: float | None = None) -> PaperDemoComparison:
        entry_difference = _delta(demo_entry, paper_entry)
        exit_difference = _delta(demo_exit, paper_exit)
        pnl_difference = _delta(demo_net_pnl, paper_net_pnl)

        reasons: list[str] = []
        if entry_difference is None:
            reasons.append("ENTRY_NOT_COMPARABLE")
        elif abs(entry_difference) > self.entry_tolerance:
            reasons.append("ENTRY_OUTSIDE_TOLERANCE")
        if exit_difference is None:
            reasons.append("EXIT_NOT_COMPARABLE")
        elif abs(exit_difference) > self.exit_tolerance:
            reasons.append("EXIT_OUTSIDE_TOLERANCE")
        if slippage is not None and abs(float(slippage)) > self.slippage_tolerance:
            reasons.append("SLIPPAGE_OUTSIDE_TOLERANCE")

        within = not reasons
        return PaperDemoComparison(
            str(request_id), str(symbol).upper(), paper_entry, demo_entry, paper_exit, demo_exit,
            entry_difference, exit_difference, spread, slippage, commission, swap,
            paper_net_pnl, demo_net_pnl, pnl_difference, within, tuple(reasons))

    # ------------------------------------------------------------ section 32
    def attribute(self, *, request_id: str, symbol: str,
                  observation_expected: float | None = None,
                  paper_result: float | None = None, demo_result: float | None = None,
                  spread: float | None = None, expected_spread: float | None = None,
                  slippage: float | None = None, model_correct: bool | None = None,
                  strategy_correct: bool | None = None,
                  risk_rejected: bool = False) -> ExecutionAttribution:
        """Split the gap between what was expected and what happened.

        The two gaps answer different questions. `observation_gap` is DEMO minus
        what the observation pipeline expected: signal quality plus execution.
        `paper_gap` is DEMO minus paper: execution alone, because paper used the
        same signal.
        """
        observation_gap = _delta(demo_result, observation_expected)
        paper_gap = _delta(demo_result, paper_result)
        errors: list[str] = []
        details: dict[str, Any] = {}

        if risk_rejected:
            errors.append(RISK_REJECTION)
        if demo_result is None:
            errors.append(NOT_COMPARABLE)
            return ExecutionAttribution(str(request_id), str(symbol).upper(), observation_expected,
                                        paper_result, demo_result, observation_gap, paper_gap,
                                        tuple(errors), details)
        if paper_gap is not None and paper_gap < 0:
            # Same signal, worse outcome: the difference is execution, not the idea.
            errors.append(EXECUTION_ERROR)
            details["execution_gap"] = round(paper_gap, 8)
        if spread is not None and expected_spread is not None and float(spread) > float(expected_spread):
            errors.append(SPREAD_ERROR)
            details["spread_excess"] = round(float(spread) - float(expected_spread), 8)
        if slippage is not None and abs(float(slippage)) > self.slippage_tolerance:
            errors.append(SLIPPAGE_ERROR)
            details["slippage"] = float(slippage)
        if observation_gap is not None and paper_gap is not None and observation_gap < paper_gap:
            # Paper already fell short of the observation: the signal itself missed.
            errors.append(SIGNAL_QUALITY_ERROR)
            details["signal_gap"] = round(observation_gap - paper_gap, 8)
        if model_correct is False:
            errors.append(MODEL_ERROR)
        if strategy_correct is False:
            errors.append(STRATEGY_ERROR)

        return ExecutionAttribution(str(request_id), str(symbol).upper(), observation_expected,
                                    paper_result, demo_result, observation_gap, paper_gap,
                                    tuple(dict.fromkeys(errors)), details)

    @staticmethod
    def summarize(comparisons: Sequence[PaperDemoComparison]) -> dict[str, Any]:
        """Aggregate execution reality across trades. Empty input reports no evidence."""
        rows = [row for row in comparisons if row is not None]
        if not rows:
            return {"samples": 0, "reliable": False, "reasons": ["NO_COMPARISONS"]}
        entries = [row.entry_difference for row in rows if row.entry_difference is not None]
        slippages = [row.slippage for row in rows if row.slippage is not None]
        pnls = [row.pnl_difference for row in rows if row.pnl_difference is not None]
        return {
            "samples": len(rows),
            "within_tolerance": sum(row.within_tolerance for row in rows),
            "mean_entry_difference": round(sum(entries) / len(entries), 8) if entries else None,
            "worst_entry_difference": round(max(entries, key=abs), 8) if entries else None,
            "mean_slippage": round(sum(slippages) / len(slippages), 8) if slippages else None,
            "mean_pnl_difference": round(sum(pnls) / len(pnls), 8) if pnls else None,
            # A handful of demo fills is an anecdote, not a measurement.
            "reliable": len(rows) >= 30,
            "reasons": [] if len(rows) >= 30 else ["INSUFFICIENT_SAMPLES"],
        }
