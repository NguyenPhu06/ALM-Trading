"""Signal weight research (section 22).

Weights are **researched, not hardcoded**. For each signal the study asks one
question on held-out forward observations: when this signal pointed a direction,
what happened net of cost?

Two properties keep the output honest:

* A signal with too few observations gets **no weight at all** — not a small
  one. A weight derived from twelve samples is a number pretending to be
  evidence.
* Weights are a *proposal*. `apply()` does not exist. Nothing in this module
  writes to `strategy.scoring.DEFAULT_WEIGHTS`, and a test asserts that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from config.settings import load_yaml
from research.conflicts import SIGNALS, direction_of
from research.metrics import PerformanceMetrics, evaluate
from research.models import ResearchObservation, require_forward_only
from research.significance import SignificanceTester

DISCLAIMER = (
    "Proposed weights are derived from out-of-sample forward observations. They "
    "are a research output, not a configuration change: applying them is a "
    "separate, deliberate decision."
)


@dataclass(frozen=True, slots=True)
class SignalEvidence:
    signal: str
    samples: int
    agreed: int = 0
    disagreed: int = 0
    metrics: PerformanceMetrics | None = None
    expectancy_when_agreed: float | None = None
    expectancy_when_disagreed: float | None = None
    accuracy_when_agreed: float | None = None
    edge: float | None = None
    significance: dict[str, Any] = field(default_factory=dict)
    reliable: bool = False

    @property
    def proposed_weight(self) -> float | None:
        """`None` — not zero — when the evidence does not support a weight."""
        if not self.reliable or self.edge is None or self.edge <= 0:
            return None
        return self.edge

    def as_dict(self) -> dict[str, Any]:
        return {"signal": self.signal, "samples": self.samples, "agreed": self.agreed,
                "disagreed": self.disagreed, "reliable": self.reliable,
                "expectancy_when_agreed": self.expectancy_when_agreed,
                "expectancy_when_disagreed": self.expectancy_when_disagreed,
                "accuracy_when_agreed": self.accuracy_when_agreed,
                "edge": self.edge, "proposed_weight": self.proposed_weight,
                "significance": dict(self.significance)}


@dataclass(frozen=True, slots=True)
class WeightProposal:
    evidence: dict[str, SignalEvidence]
    minimum_samples: int

    @property
    def weighted(self) -> dict[str, float]:
        """Normalised weights over the signals that earned one."""
        raw = {name: item.proposed_weight for name, item in self.evidence.items()
               if item.proposed_weight is not None}
        total = sum(raw.values())
        if not total:
            return {}
        return {name: value / total for name, value in sorted(raw.items())}

    @property
    def unweighted(self) -> tuple[str, ...]:
        return tuple(name for name, item in sorted(self.evidence.items())
                     if item.proposed_weight is None)

    @property
    def ranking(self) -> tuple[str, ...]:
        scored = [(name, item.edge) for name, item in self.evidence.items()
                  if item.edge is not None]
        return tuple(name for name, _ in sorted(scored, key=lambda item: item[1],
                                                reverse=True))

    def as_dict(self) -> dict[str, Any]:
        return {"minimum_samples": self.minimum_samples,
                "proposed_weights": self.weighted,
                "no_weight_assigned": list(self.unweighted),
                "ranking": list(self.ranking),
                "evidence": {name: item.as_dict()
                             for name, item in sorted(self.evidence.items())},
                "applied": False, "disclaimer": DISCLAIMER}


class SignalWeightResearch:
    def __init__(self, *, minimum_samples: int | None = None,
                 tester: SignificanceTester | None = None,
                 signals: Sequence[str] = SIGNALS):
        config = load_yaml().get("phase_15", {})
        self.minimum_samples = int(minimum_samples if minimum_samples is not None
                                   else config.get("weight_minimum_samples", 50))
        self.signals = tuple(signals)
        self.tester = tester or SignificanceTester(minimum_samples=self.minimum_samples)

    def run(self, observations: Sequence[ResearchObservation]) -> WeightProposal:
        rows = require_forward_only(observations)
        evidence: dict[str, SignalEvidence] = {}
        for signal in self.signals:
            evidence[signal] = self._evaluate(signal, rows)
        return WeightProposal(evidence, self.minimum_samples)

    def _evaluate(self, signal: str, rows: Sequence[ResearchObservation]) -> SignalEvidence:
        present = [row for row in rows if signal in (row.signals or {})]
        if not present:
            return SignalEvidence(signal, 0)

        agreed: list[ResearchObservation] = []
        disagreed: list[ResearchObservation] = []
        for row in present:
            signal_direction = direction_of((row.signals or {}).get(signal))
            taken = direction_of(row.predicted)
            if not signal_direction or not taken:
                continue
            (agreed if signal_direction == taken else disagreed).append(row)

        metrics = evaluate(present, minimum_samples=self.minimum_samples)
        agreed_metrics = evaluate(agreed, minimum_samples=self.minimum_samples)
        disagreed_metrics = evaluate(disagreed, minimum_samples=self.minimum_samples)

        significance: dict[str, Any] = {}
        edge: float | None = None
        if agreed and disagreed:
            report = self.tester.compare([row.net_pnl for row in disagreed],
                                         [row.net_pnl for row in agreed])
            significance = report.as_dict()
        if agreed_metrics.expectancy is not None and disagreed_metrics.expectancy is not None:
            edge = agreed_metrics.expectancy - disagreed_metrics.expectancy
        elif agreed_metrics.expectancy is not None and not disagreed:
            # Nothing to contrast against; the raw expectancy is not an edge.
            edge = None

        reliable = (len(agreed) >= self.minimum_samples
                    and len(disagreed) >= self.minimum_samples)
        return SignalEvidence(
            signal=signal, samples=len(present), agreed=len(agreed),
            disagreed=len(disagreed), metrics=metrics,
            expectancy_when_agreed=agreed_metrics.expectancy,
            expectancy_when_disagreed=disagreed_metrics.expectancy,
            accuracy_when_agreed=agreed_metrics.prediction_accuracy,
            edge=edge, significance=significance, reliable=reliable)

    def compare_with_configured(self, proposal: WeightProposal) -> dict[str, Any]:
        """Show the proposal next to the weights the strategy engine actually uses.

        Reporting only. Nothing here writes to the strategy configuration.
        """
        from strategy.scoring import DEFAULT_WEIGHTS

        proposed = proposal.weighted
        rows = []
        for name in sorted(set(DEFAULT_WEIGHTS) | set(proposed)):
            configured = DEFAULT_WEIGHTS.get(name)
            suggested = proposed.get(name)
            rows.append({"signal": name, "configured": configured,
                         "proposed": suggested,
                         "delta": (suggested - configured)
                         if (configured is not None and suggested is not None) else None})
        return {"comparison": rows, "applied": False, "disclaimer": DISCLAIMER}
