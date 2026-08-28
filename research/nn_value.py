"""Does the neural network earn its place? (section 13)

One comparison, stated plainly: the same strategy with the NN and without it.
Six deltas are reported, and the default answer is **NN_VALUE_NOT_PROVEN**.

The phrasing matters. "Not proven" is not "no value" — it is the honest state of
a comparison that has not cleared the bar. Either way the conclusion is the
same: the NN is not forced into the strategy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Sequence

from research.metrics import PerformanceMetrics, delta, evaluate
from research.models import ResearchObservation, require_forward_only
from research.significance import SignificanceTester, SignificanceVerdict

DELTA_FIELDS = ("expectancy", "win_rate", "maximum_drawdown", "average_mae",
                "average_mfe", "calibration")


class NNValueVerdict(StrEnum):
    NN_ADDS_VALUE = "NN_ADDS_VALUE"
    NN_VALUE_NOT_PROVEN = "NN_VALUE_NOT_PROVEN"
    NN_HARMFUL = "NN_HARMFUL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class NNValueReport:
    verdict: NNValueVerdict
    without_nn: PerformanceMetrics
    with_nn: PerformanceMetrics
    deltas: dict[str, float | None] = field(default_factory=dict)
    significance: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    @property
    def proven(self) -> bool:
        return self.verdict is NNValueVerdict.NN_ADDS_VALUE

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict), "proven": self.proven,
            "without_nn": self.without_nn.as_dict(), "with_nn": self.with_nn.as_dict(),
            "deltas": {name: self.deltas.get(name) for name in DELTA_FIELDS},
            "all_deltas": dict(self.deltas), "significance": dict(self.significance),
            "reasons": list(self.reasons),
            "note": ("The NN is not forced into the strategy. NN_VALUE_NOT_PROVEN is a "
                     "state of the evidence, not a claim that the NN is worthless."),
        }


class NNValueTest:
    def __init__(self, *, minimum_samples: int = 100,
                 tester: SignificanceTester | None = None):
        self.minimum_samples = int(minimum_samples)
        self.tester = tester or SignificanceTester(minimum_samples=minimum_samples)

    def run(self, *, without_nn: Sequence[ResearchObservation],
            with_nn: Sequence[ResearchObservation]) -> NNValueReport:
        baseline_rows = require_forward_only(without_nn)
        candidate_rows = require_forward_only(with_nn)
        baseline = evaluate(baseline_rows, minimum_samples=self.minimum_samples)
        candidate = evaluate(candidate_rows, minimum_samples=self.minimum_samples)

        report = self.tester.compare([row.net_pnl for row in baseline_rows],
                                     [row.net_pnl for row in candidate_rows])
        deltas = delta(baseline, candidate)

        if report.verdict is SignificanceVerdict.INSUFFICIENT_DATA:
            return NNValueReport(NNValueVerdict.INSUFFICIENT_DATA, baseline, candidate,
                                 deltas, report.as_dict(),
                                 (f"SAMPLE_BELOW_MINIMUM_{self.minimum_samples}",))

        reasons: list[str] = []
        improvement = deltas.get("expectancy")
        if improvement is None:
            return NNValueReport(NNValueVerdict.INSUFFICIENT_DATA, baseline, candidate,
                                 deltas, report.as_dict(), ("NO_COMPARABLE_EXPECTANCY",))

        if improvement < 0:
            reasons.append("EXPECTANCY_LOWER_WITH_NN")
            verdict = (NNValueVerdict.NN_HARMFUL if report.significant
                       else NNValueVerdict.NN_VALUE_NOT_PROVEN)
            return NNValueReport(verdict, baseline, candidate, deltas, report.as_dict(),
                                 tuple(reasons))

        if not report.significant:
            reasons.extend(report.reasons or ("DIFFERENCE_NOT_SIGNIFICANT",))
            return NNValueReport(NNValueVerdict.NN_VALUE_NOT_PROVEN, baseline, candidate,
                                 deltas, report.as_dict(), tuple(reasons))

        # A better mean that arrives with a worse drawdown is not an improvement.
        drawdown_delta = deltas.get("maximum_drawdown")
        if drawdown_delta is not None and drawdown_delta > 0:
            reasons.append("DRAWDOWN_WORSE_WITH_NN")
            return NNValueReport(NNValueVerdict.NN_VALUE_NOT_PROVEN, baseline, candidate,
                                 deltas, report.as_dict(), tuple(reasons))

        return NNValueReport(NNValueVerdict.NN_ADDS_VALUE, baseline, candidate, deltas,
                             report.as_dict())

    def split(self, observations: Sequence[ResearchObservation]) -> NNValueReport:
        """Split one set on whether the observation actually carried a prediction."""
        rows = require_forward_only(observations)
        with_nn = [row for row in rows if row.confidence is not None]
        without_nn = [row for row in rows if row.confidence is None]
        return self.run(without_nn=without_nn, with_nn=with_nn)
