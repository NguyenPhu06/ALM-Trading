"""Feature ablation and indicator value (sections 3 and 14).

The question is not "does the full model perform well" but "does each component
earn its place". Every arm is BASELINE plus exactly one component, measured
out-of-sample against the same baseline observations.

The default assumption is that a component adds nothing. It has to demonstrate
otherwise: a positive delta that is not statistically separable from zero is
reported as `NOT_PROVEN`, and a component that makes things worse is reported as
`HARMFUL` rather than quietly dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from research.metrics import PerformanceMetrics, delta, evaluate
from research.models import ResearchObservation, require_forward_only
from research.significance import SignificanceTester, SignificanceVerdict

# Section 3's arms, in the order they are reported.
ABLATION_ARMS: tuple[str, ...] = (
    "BASELINE", "BASELINE+LIQUIDITY", "BASELINE+MARKET_STRUCTURE", "BASELINE+ICHIMOKU",
    "BASELINE+RSI", "BASELINE+ADX", "BASELINE+ATR", "BASELINE+NN", "FULL_MODEL",
)

# Section 14's components, and the arm that isolates each one.
COMPONENT_ARMS: dict[str, str] = {
    "liquidity": "BASELINE+LIQUIDITY",
    "market_structure": "BASELINE+MARKET_STRUCTURE",
    "ichimoku": "BASELINE+ICHIMOKU",
    "rsi": "BASELINE+RSI",
    "adx": "BASELINE+ADX",
    "atr": "BASELINE+ATR",
    "nn": "BASELINE+NN",
}


class ComponentVerdict(StrEnum):
    IMPROVES = "IMPROVES"
    NO_IMPROVEMENT = "NO_IMPROVEMENT"
    NOT_PROVEN = "NOT_PROVEN"
    HARMFUL = "HARMFUL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class ArmResult:
    arm: str
    metrics: PerformanceMetrics
    deltas: dict[str, float | None] = field(default_factory=dict)
    verdict: ComponentVerdict = ComponentVerdict.INSUFFICIENT_DATA
    significance: dict[str, Any] = field(default_factory=dict)
    component: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"arm": self.arm, "component": self.component,
                "verdict": str(self.verdict), "metrics": self.metrics.as_dict(),
                "deltas": dict(self.deltas), "significance": dict(self.significance)}


@dataclass(frozen=True, slots=True)
class AblationReport:
    baseline: PerformanceMetrics
    arms: dict[str, ArmResult]
    minimum_samples: int

    def _named(self, verdict: ComponentVerdict) -> tuple[str, ...]:
        return tuple(name for name, arm in sorted(self.arms.items())
                     if arm.verdict is verdict)

    @property
    def improving(self) -> tuple[str, ...]:
        return self._named(ComponentVerdict.IMPROVES)

    @property
    def harmful(self) -> tuple[str, ...]:
        return self._named(ComponentVerdict.HARMFUL)

    @property
    def unproven(self) -> tuple[str, ...]:
        return self._named(ComponentVerdict.NOT_PROVEN)

    @property
    def best_arm(self) -> str | None:
        scored = [(name, arm.metrics.expectancy) for name, arm in self.arms.items()
                  if arm.metrics.expectancy is not None and arm.metrics.reliable]
        return max(scored, key=lambda item: item[1])[0] if scored else None

    def as_dict(self) -> dict[str, Any]:
        return {"baseline": self.baseline.as_dict(),
                "minimum_samples": self.minimum_samples,
                "improving": list(self.improving), "harmful": list(self.harmful),
                "not_proven": list(self.unproven), "best_arm": self.best_arm,
                "arms": {name: arm.as_dict() for name, arm in sorted(self.arms.items())},
                "note": ("More components is not assumed better. Each arm must beat "
                         "BASELINE out-of-sample to be reported as IMPROVES.")}


class AblationStudy:
    def __init__(self, *, minimum_samples: int = 30,
                 tester: SignificanceTester | None = None):
        self.minimum_samples = int(minimum_samples)
        self.tester = tester or SignificanceTester(minimum_samples=minimum_samples)

    def run(self, arms: Mapping[str, Sequence[ResearchObservation]], *,
            baseline_arm: str = "BASELINE") -> AblationReport:
        if baseline_arm not in arms:
            raise KeyError(f"ablation needs a {baseline_arm} arm")

        baseline_rows = require_forward_only(arms[baseline_arm])
        baseline = evaluate(baseline_rows, minimum_samples=self.minimum_samples)
        baseline_returns = [row.net_pnl for row in baseline_rows]

        results: dict[str, ArmResult] = {}
        for name, observations in arms.items():
            rows = require_forward_only(observations)
            metrics = evaluate(rows, minimum_samples=self.minimum_samples)
            if name == baseline_arm:
                results[name] = ArmResult(name, metrics, {}, ComponentVerdict.NO_IMPROVEMENT,
                                          {"note": "baseline"}, component=None)
                continue
            report = self.tester.compare(baseline_returns, [row.net_pnl for row in rows])
            results[name] = ArmResult(
                arm=name, metrics=metrics, deltas=delta(baseline, metrics),
                verdict=self._verdict(baseline, metrics, report),
                significance=report.as_dict(),
                component=_component_for(name))
        return AblationReport(baseline, results, self.minimum_samples)

    def _verdict(self, baseline: PerformanceMetrics, arm: PerformanceMetrics,
                 report: Any) -> ComponentVerdict:
        if not arm.reliable or report.verdict is SignificanceVerdict.INSUFFICIENT_DATA:
            return ComponentVerdict.INSUFFICIENT_DATA
        if arm.expectancy is None or baseline.expectancy is None:
            return ComponentVerdict.INSUFFICIENT_DATA
        difference = arm.expectancy - baseline.expectancy
        if difference < 0:
            # Losing to the baseline is reported, not dropped.
            return (ComponentVerdict.HARMFUL if report.significant
                    else ComponentVerdict.NO_IMPROVEMENT)
        if not report.significant:
            # Better on paper, indistinguishable from noise.
            return ComponentVerdict.NOT_PROVEN
        return ComponentVerdict.IMPROVES

    # -------------------------------------------------- 14. component value
    def component_value(self, arms: Mapping[str, Sequence[ResearchObservation]], *,
                        baseline_arm: str = "BASELINE") -> dict[str, Any]:
        """Incremental contribution of each named component, one arm each."""
        report = self.run(arms, baseline_arm=baseline_arm)
        components: dict[str, Any] = {}
        for component, arm_name in COMPONENT_ARMS.items():
            arm = report.arms.get(arm_name)
            if arm is None:
                components[component] = {"verdict": str(ComponentVerdict.INSUFFICIENT_DATA),
                                         "reason": "ARM_NOT_RUN"}
                continue
            components[component] = {
                "arm": arm_name, "verdict": str(arm.verdict),
                "delta_expectancy": arm.deltas.get("expectancy"),
                "delta_win_rate": arm.deltas.get("win_rate"),
                "delta_drawdown": arm.deltas.get("maximum_drawdown"),
                "effect_size": arm.significance.get("effect_size"),
                "effect_band": arm.significance.get("effect_band"),
                "sample_size": arm.metrics.sample_size,
            }
        ranked = sorted(
            ((name, payload.get("delta_expectancy")) for name, payload
             in components.items() if payload.get("delta_expectancy") is not None),
            key=lambda item: item[1], reverse=True)
        return {
            "components": components,
            "ranking": [name for name, _ in ranked],
            "most_valuable": ranked[0][0] if ranked else None,
            "proven": [name for name, payload in components.items()
                       if payload.get("verdict") == str(ComponentVerdict.IMPROVES)],
            "unproven": [name for name, payload in components.items()
                         if payload.get("verdict") in {str(ComponentVerdict.NOT_PROVEN),
                                                       str(ComponentVerdict.NO_IMPROVEMENT)}],
            "harmful": [name for name, payload in components.items()
                        if payload.get("verdict") == str(ComponentVerdict.HARMFUL)],
            "disclaimer": ("Incremental contribution measured on forward observations. "
                           "It does not establish that the component causes the change."),
        }


def _component_for(arm: str) -> str | None:
    for component, name in COMPONENT_ARMS.items():
        if name == arm:
            return component
    return None
