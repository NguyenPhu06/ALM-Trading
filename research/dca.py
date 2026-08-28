"""DCA research (section 11).

DCA is not assumed to help. It reliably raises win rate — averaging down turns
small losses into small wins — while moving the loss that remains into the tail.
A configuration that buys a higher win rate with a materially worse tail is
**rejected**, and that rule is applied here rather than left to judgement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from config.settings import load_yaml
from research.metrics import PerformanceMetrics, delta, evaluate, tail_loss
from research.models import ResearchObservation, require_forward_only
from research.significance import SignificanceTester

# Section 11's arms, in the order they are reported.
DCA_ARMS: tuple[str, ...] = ("NO_DCA", "DCA_1", "DCA_2", "DCA_3")


class DCAVerdict(StrEnum):
    IMPROVES = "IMPROVES"
    NO_IMPROVEMENT = "NO_IMPROVEMENT"
    REJECTED_TAIL_RISK = "REJECTED_TAIL_RISK"
    HARMFUL = "HARMFUL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


def arm_for(levels: int) -> str:
    levels = int(levels or 0)
    return "NO_DCA" if levels <= 0 else f"DCA_{min(levels, 3)}"


@dataclass(frozen=True, slots=True)
class DCAArm:
    name: str
    levels: int
    metrics: PerformanceMetrics
    tail_loss: float | None = None
    average_margin: float | None = None
    worst_mae: float | None = None
    deltas: dict[str, float | None] = field(default_factory=dict)
    verdict: DCAVerdict = DCAVerdict.INSUFFICIENT_DATA
    reasons: tuple[str, ...] = ()
    significance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "levels": self.levels, "verdict": str(self.verdict),
                "metrics": self.metrics.as_dict(), "tail_loss": self.tail_loss,
                "average_margin": self.average_margin, "worst_mae": self.worst_mae,
                "deltas": dict(self.deltas), "reasons": list(self.reasons),
                "significance": dict(self.significance)}


@dataclass(frozen=True, slots=True)
class DCAReport:
    baseline: PerformanceMetrics
    arms: dict[str, DCAArm]
    tail_tolerance: float
    minimum_samples: int

    @property
    def accepted(self) -> tuple[str, ...]:
        return tuple(name for name, arm in sorted(self.arms.items())
                     if arm.verdict is DCAVerdict.IMPROVES)

    @property
    def rejected(self) -> tuple[str, ...]:
        return tuple(name for name, arm in sorted(self.arms.items())
                     if arm.verdict in {DCAVerdict.REJECTED_TAIL_RISK, DCAVerdict.HARMFUL})

    @property
    def recommended(self) -> str:
        """NO_DCA unless something demonstrably beats it."""
        candidates = [(name, self.arms[name].metrics.expectancy)
                      for name in self.accepted
                      if self.arms[name].metrics.expectancy is not None]
        return max(candidates, key=lambda item: item[1])[0] if candidates else "NO_DCA"

    def as_dict(self) -> dict[str, Any]:
        return {"baseline": self.baseline.as_dict(),
                "tail_tolerance": self.tail_tolerance,
                "minimum_samples": self.minimum_samples,
                "accepted": list(self.accepted), "rejected": list(self.rejected),
                "recommended": self.recommended,
                "arms": {name: arm.as_dict() for name, arm in sorted(self.arms.items())},
                "note": ("A DCA configuration is rejected when it raises win rate while "
                         "materially worsening tail risk or drawdown.")}


class DCAResearch:
    def __init__(self, *, minimum_samples: int = 30, tail_tolerance: float | None = None,
                 tester: SignificanceTester | None = None):
        config = load_yaml().get("phase_15", {}).get("dca", {})
        self.minimum_samples = int(minimum_samples)
        # How much worse the tail may get before the arm is rejected outright.
        self.tail_tolerance = float(tail_tolerance if tail_tolerance is not None
                                    else config.get("tail_tolerance", 0.20))
        self.tester = tester or SignificanceTester(minimum_samples=minimum_samples)

    def by_levels(self, observations: Sequence[ResearchObservation]
                  ) -> dict[str, list[ResearchObservation]]:
        grouped: dict[str, list[ResearchObservation]] = {name: [] for name in DCA_ARMS}
        for row in require_forward_only(observations):
            grouped.setdefault(arm_for(row.dca_levels), []).append(row)
        return grouped

    def run(self, observations: Sequence[ResearchObservation] | None = None, *,
            arms: Mapping[str, Sequence[ResearchObservation]] | None = None,
            baseline_arm: str = "NO_DCA") -> DCAReport:
        grouped = dict(arms) if arms is not None else self.by_levels(observations or ())
        if baseline_arm not in grouped:
            raise KeyError(f"DCA research needs a {baseline_arm} arm")

        baseline_rows = require_forward_only(grouped[baseline_arm])
        baseline = evaluate(baseline_rows, minimum_samples=self.minimum_samples)
        baseline_returns = [row.net_pnl for row in baseline_rows]
        baseline_tail = tail_loss(baseline_returns)

        results: dict[str, DCAArm] = {}
        for name, rows in grouped.items():
            observations_ = require_forward_only(rows)
            metrics = evaluate(observations_, minimum_samples=self.minimum_samples)
            returns = [row.net_pnl for row in observations_]
            margins = [row.margin_used for row in observations_
                       if row.margin_used is not None]
            arm_tail = tail_loss(returns)

            if name == baseline_arm:
                results[name] = DCAArm(name, 0, metrics, arm_tail,
                                       (sum(margins) / len(margins)) if margins else None,
                                       metrics.worst_mae, {},
                                       DCAVerdict.NO_IMPROVEMENT, ("baseline",))
                continue

            report = self.tester.compare(baseline_returns, returns)
            verdict, reasons = self._verdict(baseline, metrics, baseline_tail, arm_tail,
                                             report)
            results[name] = DCAArm(
                name=name, levels=_levels_for(name), metrics=metrics, tail_loss=arm_tail,
                average_margin=(sum(margins) / len(margins)) if margins else None,
                worst_mae=metrics.worst_mae, deltas=delta(baseline, metrics),
                verdict=verdict, reasons=reasons, significance=report.as_dict())
        return DCAReport(baseline, results, self.tail_tolerance, self.minimum_samples)

    def _verdict(self, baseline: PerformanceMetrics, arm: PerformanceMetrics,
                 baseline_tail: float | None, arm_tail: float | None,
                 report: Any) -> tuple[DCAVerdict, tuple[str, ...]]:
        if not arm.reliable or arm.expectancy is None or baseline.expectancy is None:
            return DCAVerdict.INSUFFICIENT_DATA, ("SAMPLE_TOO_SMALL",)

        reasons: list[str] = []
        win_rate_up = (arm.win_rate or 0) > (baseline.win_rate or 0)

        tail_worse = False
        if baseline_tail is not None and arm_tail is not None and baseline_tail < 0:
            # Both are negative; "worse" means further below zero.
            tail_worse = arm_tail < baseline_tail * (1.0 + self.tail_tolerance)
        drawdown_worse = (baseline.maximum_drawdown is not None
                          and arm.maximum_drawdown is not None
                          and arm.maximum_drawdown > baseline.maximum_drawdown
                          * (1.0 + self.tail_tolerance))

        # The rule section 11 asks for, stated directly.
        if win_rate_up and (tail_worse or drawdown_worse):
            if tail_worse:
                reasons.append("TAIL_RISK_WORSE")
            if drawdown_worse:
                reasons.append("DRAWDOWN_WORSE")
            reasons.append("WIN_RATE_BOUGHT_WITH_TAIL_RISK")
            return DCAVerdict.REJECTED_TAIL_RISK, tuple(reasons)

        if arm.expectancy < baseline.expectancy:
            return (DCAVerdict.HARMFUL if report.significant
                    else DCAVerdict.NO_IMPROVEMENT), ("EXPECTANCY_LOWER",)
        if not report.significant:
            return DCAVerdict.NO_IMPROVEMENT, ("DIFFERENCE_NOT_SIGNIFICANT",)
        return DCAVerdict.IMPROVES, ()

    # ----------------------------------------------------- spacing / exposure
    def by_spacing(self, observations: Sequence[ResearchObservation]) -> dict[str, Any]:
        """Group by the configured spacing recorded on each observation."""
        grouped = segment(require_forward_only(observations), "exit_kind") \
            if False else {}
        buckets: dict[str, list[ResearchObservation]] = {}
        for row in require_forward_only(observations):
            spacing = row.context.get("dca_spacing") if row.context else None
            buckets.setdefault(str(spacing), []).append(row)
        return {"spacing": {name: evaluate(rows,
                                           minimum_samples=self.minimum_samples).as_dict()
                            for name, rows in sorted(buckets.items())},
                "note": "Spacing is read from the observation context, never assumed."}

    def by_exposure(self, observations: Sequence[ResearchObservation]) -> dict[str, Any]:
        buckets: dict[str, list[ResearchObservation]] = {}
        for row in require_forward_only(observations):
            limit = row.context.get("exposure_limit") if row.context else None
            buckets.setdefault(str(limit), []).append(row)
        return {"exposure": {name: evaluate(rows,
                                            minimum_samples=self.minimum_samples).as_dict()
                             for name, rows in sorted(buckets.items())},
                "margin_note": ("Margin usage is reported per arm; an arm with no margin "
                                "data reports None rather than zero.")}


def _levels_for(name: str) -> int:
    tail = name.rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0
