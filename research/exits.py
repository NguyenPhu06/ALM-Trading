"""Time-exit and exit-rule research (section 12).

Seven exit families, compared on forward observations rather than on intuition.
The comparison that matters is not "which exit wins most often" but "which exit
keeps the most of what MFE offered" — an exit that captures a small fraction of
the favourable excursion is leaving the trade's value on the table, however good
its win rate looks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from research.metrics import PerformanceMetrics, delta, evaluate
from research.models import ResearchObservation, require_forward_only
from research.significance import SignificanceTester

# Section 12's list, in the order they are reported.
EXIT_KINDS: tuple[str, ...] = ("FIXED_STOP", "FIXED_TARGET", "TIME_EXIT",
                               "EVEN_HOUR_EXIT", "STRUCTURE_EXIT", "LIQUIDITY_EXIT",
                               "HYBRID_EXIT")


class ExitVerdict(StrEnum):
    BEST = "BEST"
    COMPETITIVE = "COMPETITIVE"
    WORSE = "WORSE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class ExitArm:
    kind: str
    metrics: PerformanceMetrics
    capture_ratio: float | None = None
    average_holding: float | None = None
    verdict: ExitVerdict = ExitVerdict.INSUFFICIENT_DATA
    deltas: dict[str, float | None] = field(default_factory=dict)
    significance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "verdict": str(self.verdict),
                "metrics": self.metrics.as_dict(), "capture_ratio": self.capture_ratio,
                "average_holding": self.average_holding, "deltas": dict(self.deltas),
                "significance": dict(self.significance)}


@dataclass(frozen=True, slots=True)
class ExitReport:
    arms: dict[str, ExitArm]
    reference: str
    minimum_samples: int

    @property
    def best(self) -> str | None:
        scored = [(name, arm.metrics.expectancy) for name, arm in self.arms.items()
                  if arm.metrics.reliable and arm.metrics.expectancy is not None]
        return max(scored, key=lambda item: item[1])[0] if scored else None

    @property
    def best_capture(self) -> str | None:
        scored = [(name, arm.capture_ratio) for name, arm in self.arms.items()
                  if arm.metrics.reliable and arm.capture_ratio is not None]
        return max(scored, key=lambda item: item[1])[0] if scored else None

    @property
    def unreliable(self) -> tuple[str, ...]:
        return tuple(name for name, arm in sorted(self.arms.items())
                     if not arm.metrics.reliable)

    def as_dict(self) -> dict[str, Any]:
        return {"reference": self.reference, "minimum_samples": self.minimum_samples,
                "best": self.best, "best_capture": self.best_capture,
                "unreliable": list(self.unreliable),
                "arms": {name: arm.as_dict() for name, arm in sorted(self.arms.items())},
                "note": ("capture_ratio is realised net return over the favourable "
                         "excursion the trade offered; a high win rate with a low "
                         "capture ratio means the exit left value behind.")}


def capture_ratio(observations: Sequence[ResearchObservation]) -> float | None:
    """How much of the available MFE the exit actually realised."""
    rows = [row for row in observations if row.mfe not in (None, 0)]
    if not rows:
        return None
    available = sum(abs(row.mfe) for row in rows)
    if not available:
        return None
    return sum(row.net_pnl for row in rows) / available


class ExitResearch:
    def __init__(self, *, minimum_samples: int = 30,
                 tester: SignificanceTester | None = None):
        self.minimum_samples = int(minimum_samples)
        self.tester = tester or SignificanceTester(minimum_samples=minimum_samples)

    def by_kind(self, observations: Sequence[ResearchObservation]
                ) -> dict[str, list[ResearchObservation]]:
        grouped: dict[str, list[ResearchObservation]] = {name: [] for name in EXIT_KINDS}
        for row in require_forward_only(observations):
            name = str(row.exit_kind or "UNKNOWN").upper()
            grouped.setdefault(name, []).append(row)
        return grouped

    def run(self, observations: Sequence[ResearchObservation] | None = None, *,
            arms: Mapping[str, Sequence[ResearchObservation]] | None = None,
            reference: str = "TIME_EXIT") -> ExitReport:
        grouped = dict(arms) if arms is not None else self.by_kind(observations or ())
        reference_rows = require_forward_only(grouped.get(reference, ()))
        reference_returns = [row.net_pnl for row in reference_rows]
        reference_metrics = evaluate(reference_rows, minimum_samples=self.minimum_samples)

        results: dict[str, ExitArm] = {}
        for name, rows in grouped.items():
            items = require_forward_only(rows)
            metrics = evaluate(items, minimum_samples=self.minimum_samples)
            holdings = [row.holding_time for row in items if row.holding_time is not None]
            significance: dict[str, Any] = {}
            deltas: dict[str, float | None] = {}
            if name != reference and reference_returns:
                report = self.tester.compare(reference_returns,
                                             [row.net_pnl for row in items])
                significance = report.as_dict()
                deltas = delta(reference_metrics, metrics)
            results[name] = ExitArm(
                kind=name, metrics=metrics, capture_ratio=capture_ratio(items),
                average_holding=(sum(holdings) / len(holdings)) if holdings else None,
                verdict=ExitVerdict.INSUFFICIENT_DATA, deltas=deltas,
                significance=significance)

        report = ExitReport(results, reference, self.minimum_samples)
        return ExitReport(self._verdicts(results, report.best), reference,
                          self.minimum_samples)

    @staticmethod
    def _verdicts(arms: dict[str, ExitArm], best: str | None) -> dict[str, ExitArm]:
        from dataclasses import replace

        decided: dict[str, ExitArm] = {}
        best_expectancy = (arms[best].metrics.expectancy if best else None)
        for name, arm in arms.items():
            if not arm.metrics.reliable or arm.metrics.expectancy is None:
                decided[name] = replace(arm, verdict=ExitVerdict.INSUFFICIENT_DATA)
                continue
            if name == best:
                decided[name] = replace(arm, verdict=ExitVerdict.BEST)
                continue
            significant = bool(arm.significance.get("significant"))
            decided[name] = replace(
                arm, verdict=ExitVerdict.WORSE if significant else ExitVerdict.COMPETITIVE)
        return decided
