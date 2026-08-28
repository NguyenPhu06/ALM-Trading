"""Strategy champion / challenger (section 4).

A challenger replaces the champion only after clearing five gates, in order:

    1. out-of-sample evaluation      (forward observations, never a backtest)
    2. walk-forward validation       (consistent across windows)
    3. sufficient sample size        (both arms)
    4. risk-adjusted comparison      (expectancy AND drawdown, not just PnL)
    5. stability analysis            (regime and session, not just aggregate)

Clearing all five produces a **recommendation**. Promotion itself still needs a
named human — `StrategyRegistry.promote()` will not accept anything else.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Sequence

from research.matrices import MatrixBuilder
from research.metrics import PerformanceMetrics, delta, evaluate
from research.models import ResearchObservation, require_forward_only
from research.significance import SignificanceTester, SignificanceVerdict


class Gate(StrEnum):
    OUT_OF_SAMPLE = "OUT_OF_SAMPLE"
    WALK_FORWARD = "WALK_FORWARD"
    SAMPLE_SIZE = "SAMPLE_SIZE"
    RISK_ADJUSTED = "RISK_ADJUSTED"
    STABILITY = "STABILITY"


GATES: tuple[Gate, ...] = (Gate.OUT_OF_SAMPLE, Gate.WALK_FORWARD, Gate.SAMPLE_SIZE,
                           Gate.RISK_ADJUSTED, Gate.STABILITY)


class ChallengerVerdict(StrEnum):
    RECOMMEND_PROMOTION = "RECOMMEND_PROMOTION"
    KEEP_CHAMPION = "KEEP_CHAMPION"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECT_CHALLENGER = "REJECT_CHALLENGER"


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: Gate
    passed: bool
    detail: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"gate": str(self.gate), "passed": self.passed, "detail": self.detail,
                **self.data}


@dataclass(frozen=True, slots=True)
class ChallengerReport:
    verdict: ChallengerVerdict
    champion: PerformanceMetrics
    challenger: PerformanceMetrics
    gates: tuple[GateResult, ...] = ()
    deltas: dict[str, float | None] = field(default_factory=dict)
    significance: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    champion_key: str | None = None
    challenger_key: str | None = None

    @property
    def recommend_promotion(self) -> bool:
        return self.verdict is ChallengerVerdict.RECOMMEND_PROMOTION

    # Stated as a property so no caller can mistake a recommendation for a promotion.
    @property
    def promoted(self) -> bool:
        return False

    @property
    def failed_gates(self) -> tuple[str, ...]:
        return tuple(str(gate.gate) for gate in self.gates if not gate.passed)

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": str(self.verdict),
                "recommend_promotion": self.recommend_promotion,
                "promoted": False, "requires_human_approval": True,
                "champion_key": self.champion_key,
                "challenger_key": self.challenger_key,
                "champion": self.champion.as_dict(),
                "challenger": self.challenger.as_dict(),
                "gates": [gate.as_dict() for gate in self.gates],
                "failed_gates": list(self.failed_gates),
                "deltas": dict(self.deltas), "significance": dict(self.significance),
                "reasons": list(self.reasons)}


class StrategyChallengerEvaluator:
    def __init__(self, *, minimum_samples: int = 100, minimum_reliable_segments: int = 1,
                 tester: SignificanceTester | None = None,
                 matrices: MatrixBuilder | None = None):
        self.minimum_samples = int(minimum_samples)
        self.minimum_reliable_segments = int(minimum_reliable_segments)
        self.tester = tester or SignificanceTester(minimum_samples=minimum_samples)
        self.matrices = matrices or MatrixBuilder()

    def evaluate(self, *, champion: Sequence[ResearchObservation],
                 challenger: Sequence[ResearchObservation],
                 champion_windows: Sequence[float] | None = None,
                 challenger_windows: Sequence[float] | None = None,
                 champion_key: str | None = None,
                 challenger_key: str | None = None) -> ChallengerReport:
        champion_rows = require_forward_only(champion)
        challenger_rows = require_forward_only(challenger)
        champion_metrics = evaluate(champion_rows, minimum_samples=self.minimum_samples)
        challenger_metrics = evaluate(challenger_rows, minimum_samples=self.minimum_samples)

        significance = self.tester.compare([row.net_pnl for row in champion_rows],
                                           [row.net_pnl for row in challenger_rows])

        gates = (
            self._out_of_sample(champion_rows, challenger_rows),
            self._walk_forward(challenger_windows),
            self._sample_size(champion_metrics, challenger_metrics),
            self._risk_adjusted(champion_metrics, challenger_metrics, significance),
            self._stability(challenger_rows),
        )

        reasons = tuple(f"{gate.gate}:{gate.detail}" for gate in gates
                        if not gate.passed and gate.detail)
        verdict = self._verdict(gates, champion_metrics, challenger_metrics, significance)
        return ChallengerReport(
            verdict=verdict, champion=champion_metrics, challenger=challenger_metrics,
            gates=gates, deltas=delta(champion_metrics, challenger_metrics),
            significance=significance.as_dict(), reasons=reasons,
            champion_key=champion_key, challenger_key=challenger_key)

    # ------------------------------------------------------------------ gates
    @staticmethod
    def _out_of_sample(champion: Sequence[ResearchObservation],
                       challenger: Sequence[ResearchObservation]) -> GateResult:
        """Both arms must be forward evidence, and must not be the same rows."""
        champion_ids = {row.observation_id for row in champion}
        challenger_ids = {row.observation_id for row in challenger}
        overlap = champion_ids & challenger_ids
        if not challenger:
            return GateResult(Gate.OUT_OF_SAMPLE, False, "NO_CHALLENGER_OBSERVATIONS")
        return GateResult(Gate.OUT_OF_SAMPLE, True, None,
                          {"champion_rows": len(champion), "challenger_rows": len(challenger),
                           "shared_observations": len(overlap),
                           "evidence": "FORWARD_OBSERVATION"})

    @staticmethod
    def _walk_forward(windows: Sequence[float] | None) -> GateResult:
        if not windows:
            return GateResult(Gate.WALK_FORWARD, False, "NO_WALK_FORWARD_WINDOWS")
        values = [float(value) for value in windows]
        best, worst = max(values), min(values)
        ratio = (worst / best) if best else 0.0
        passed = worst > 0 and ratio >= 0.5
        return GateResult(Gate.WALK_FORWARD, passed,
                          None if passed else "WALK_FORWARD_INCONSISTENT",
                          {"windows": len(values), "min": worst, "max": best,
                           "stability": ratio})

    def _sample_size(self, champion: PerformanceMetrics,
                     challenger: PerformanceMetrics) -> GateResult:
        passed = (challenger.sample_size >= self.minimum_samples
                  and champion.sample_size >= self.minimum_samples)
        return GateResult(Gate.SAMPLE_SIZE, passed,
                          None if passed else f"BELOW_MINIMUM_{self.minimum_samples}",
                          {"champion": champion.sample_size,
                           "challenger": challenger.sample_size,
                           "minimum": self.minimum_samples})

    @staticmethod
    def _risk_adjusted(champion: PerformanceMetrics, challenger: PerformanceMetrics,
                       significance: Any) -> GateResult:
        """Better returns are not enough: drawdown must not get worse."""
        failures: list[str] = []
        if (challenger.expectancy or 0) <= (champion.expectancy or 0):
            failures.append("EXPECTANCY_NOT_BETTER")
        champion_drawdown = champion.maximum_drawdown
        challenger_drawdown = challenger.maximum_drawdown
        if (champion_drawdown is not None and challenger_drawdown is not None
                and challenger_drawdown > champion_drawdown):
            failures.append("DRAWDOWN_WORSE")
        if significance.verdict is not SignificanceVerdict.SIGNIFICANT:
            failures.append(f"DIFFERENCE_{significance.verdict}")
        return GateResult(Gate.RISK_ADJUSTED, not failures,
                          ", ".join(failures) or None,
                          {"champion_expectancy": champion.expectancy,
                           "challenger_expectancy": challenger.expectancy,
                           "champion_drawdown": champion_drawdown,
                           "challenger_drawdown": challenger_drawdown,
                           "champion_sharpe_like": champion.sharpe_like,
                           "challenger_sharpe_like": challenger.sharpe_like})

    def _stability(self, challenger: Sequence[ResearchObservation]) -> GateResult:
        """An aggregate win carried by one regime or session is not stability."""
        regime = self.matrices.regime(challenger)
        session = self.matrices.session(challenger)
        reliable = len(regime.reliable_cells) + len(session.reliable_cells)
        losing = list(regime.losing) + list(session.losing)
        passed = reliable >= self.minimum_reliable_segments and not losing
        detail = None
        if reliable < self.minimum_reliable_segments:
            detail = "NO_RELIABLE_SEGMENT"
        elif losing:
            detail = f"LOSING_SEGMENTS:{','.join(losing)}"
        return GateResult(Gate.STABILITY, passed, detail,
                          {"reliable_regimes": list(regime.reliable_cells),
                           "reliable_sessions": list(session.reliable_cells),
                           "losing_segments": losing})

    @staticmethod
    def _verdict(gates: Sequence[GateResult], champion: PerformanceMetrics,
                 challenger: PerformanceMetrics, significance: Any) -> ChallengerVerdict:
        failed = [gate for gate in gates if not gate.passed]
        if not failed:
            return ChallengerVerdict.RECOMMEND_PROMOTION
        if any(gate.gate is Gate.SAMPLE_SIZE for gate in failed) \
                or significance.verdict is SignificanceVerdict.INSUFFICIENT_DATA:
            return ChallengerVerdict.INSUFFICIENT_EVIDENCE
        # A challenger that is genuinely worse is a rejection, not a "keep looking".
        if (significance.verdict is SignificanceVerdict.SIGNIFICANT
                and (challenger.expectancy or 0) < (champion.expectancy or 0)):
            return ChallengerVerdict.REJECT_CHALLENGER
        return ChallengerVerdict.KEEP_CHAMPION


def rejection_criteria() -> dict[str, Any]:
    """Section 10: when a strategy or model should be rejected, stated once."""
    return {
        "criteria": [
            "Negative expectancy on forward observations with a sufficient sample.",
            "Significantly worse than the incumbent champion on risk-adjusted terms.",
            "Profitable only in one regime or one session (no stability).",
            "Confidence materially above accuracy (systematically overconfident).",
            "Performance that does not survive multiple-testing correction.",
            "Results reproducible only by re-reading the holdout.",
        ],
        "note": ("Rejection is recorded with a stated reason and is terminal: "
                 "StrategyRegistry.reject() allows no transition out of REJECTED."),
    }
