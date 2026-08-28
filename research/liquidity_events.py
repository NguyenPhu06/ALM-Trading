"""Liquidity event study (section 19).

Seven event types, and one rule that outranks every result: **do not claim
institutional activity**. A sweep is a price pattern. What follows it is a
measurement. Neither is evidence that a fund did anything, and the language used
to report them says so.

Every finding is phrased as "what happened after", never "what they did".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from config.settings import load_yaml
from research.metrics import PerformanceMetrics, evaluate
from research.models import ResearchObservation, require_forward_only
from research.significance import SignificanceTester

# Section 19's list, in the order they are reported.
EVENT_TYPES: tuple[str, ...] = (
    "LIQUIDITY_SWEEP", "EQUAL_HIGH_SWEEP", "EQUAL_LOW_SWEEP",
    "PREVIOUS_DAY_HIGH_SWEEP", "PREVIOUS_DAY_LOW_SWEEP",
    "SESSION_HIGH_SWEEP", "SESSION_LOW_SWEEP",
)

DISCLAIMER = (
    "These are measurements of what followed an observed price pattern. They are "
    "not evidence of institutional activity, and no claim is made that any "
    "specific participant acted at any specific level."
)

# Phrases this module must never emit. Asserted by the tests.
FORBIDDEN_CLAIMS = ("institution", "smart money", "bank bought", "bank sold",
                    "fund bought", "fund sold", "whale")


@dataclass(frozen=True, slots=True)
class EventResult:
    event: str
    metrics: PerformanceMetrics
    follow_through_rate: float | None = None
    reversal_rate: float | None = None
    average_mfe: float | None = None
    average_mae: float | None = None
    significance: dict[str, Any] = field(default_factory=dict)

    @property
    def reliable(self) -> bool:
        return self.metrics.reliable

    def as_dict(self) -> dict[str, Any]:
        return {"event": self.event, "reliable": self.reliable,
                "sample_size": self.metrics.sample_size,
                "metrics": self.metrics.as_dict(),
                "follow_through_rate": self.follow_through_rate,
                "reversal_rate": self.reversal_rate,
                "average_mfe": self.average_mfe, "average_mae": self.average_mae,
                "significance": dict(self.significance),
                "claim": "OBSERVED_PATTERN_ONLY"}


@dataclass(frozen=True, slots=True)
class EventStudyReport:
    events: dict[str, EventResult]
    baseline: PerformanceMetrics
    minimum_samples: int

    @property
    def reliable_events(self) -> tuple[str, ...]:
        return tuple(name for name, item in sorted(self.events.items()) if item.reliable)

    @property
    def significant_events(self) -> tuple[str, ...]:
        return tuple(name for name, item in sorted(self.events.items())
                     if item.reliable and item.significance.get("significant"))

    @property
    def best(self) -> str | None:
        scored = [(name, item.metrics.expectancy) for name, item in self.events.items()
                  if item.reliable and item.metrics.expectancy is not None]
        return max(scored, key=lambda item: item[1])[0] if scored else None

    def as_dict(self) -> dict[str, Any]:
        return {"minimum_samples": self.minimum_samples,
                "baseline": self.baseline.as_dict(),
                "reliable_events": list(self.reliable_events),
                "significant_events": list(self.significant_events),
                "best": self.best,
                "events": {name: item.as_dict()
                           for name, item in sorted(self.events.items())},
                "disclaimer": DISCLAIMER}


class LiquidityEventStudy:
    def __init__(self, *, minimum_samples: int | None = None,
                 tester: SignificanceTester | None = None):
        config = load_yaml().get("phase_15", {})
        self.minimum_samples = int(minimum_samples if minimum_samples is not None
                                   else config.get("event_minimum_samples", 30))
        self.tester = tester or SignificanceTester(minimum_samples=self.minimum_samples)

    def by_event(self, observations: Sequence[ResearchObservation]
                 ) -> dict[str, list[ResearchObservation]]:
        grouped: dict[str, list[ResearchObservation]] = {name: [] for name in EVENT_TYPES}
        for row in require_forward_only(observations):
            if not row.liquidity_event:
                continue
            grouped.setdefault(str(row.liquidity_event).upper(), []).append(row)
        return grouped

    def run(self, observations: Sequence[ResearchObservation] | None = None, *,
            events: Mapping[str, Sequence[ResearchObservation]] | None = None,
            baseline: Sequence[ResearchObservation] | None = None) -> EventStudyReport:
        rows = require_forward_only(observations or ())
        grouped = dict(events) if events is not None else self.by_event(rows)
        baseline_rows = require_forward_only(
            baseline if baseline is not None
            else [row for row in rows if not row.liquidity_event])
        baseline_metrics = evaluate(baseline_rows, minimum_samples=self.minimum_samples)
        baseline_returns = [row.net_pnl for row in baseline_rows]

        results: dict[str, EventResult] = {}
        for name, items in grouped.items():
            observations_ = require_forward_only(items)
            metrics = evaluate(observations_, minimum_samples=self.minimum_samples)
            significance: dict[str, Any] = {}
            if baseline_returns and observations_:
                significance = self.tester.compare(
                    baseline_returns, [row.net_pnl for row in observations_]).as_dict()
            results[name] = EventResult(
                event=name, metrics=metrics,
                follow_through_rate=_rate(observations_, follow_through=True),
                reversal_rate=_rate(observations_, follow_through=False),
                average_mfe=metrics.average_mfe, average_mae=metrics.average_mae,
                significance=significance)
        return EventStudyReport(results, baseline_metrics, self.minimum_samples)


def _rate(observations: Sequence[ResearchObservation], *,
          follow_through: bool) -> float | None:
    """Share of observations that continued (or reversed) after the event.

    "Continued" means the market moved in the direction the observation
    predicted. It is a description of price, not of intent.
    """
    rows = [row for row in observations if row.correct is not None]
    if not rows:
        return None
    matching = sum(1 for row in rows if row.correct is follow_through)
    return matching / len(rows)
