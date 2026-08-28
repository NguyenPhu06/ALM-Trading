"""Model error lab (section 20).

The ten reports section 20 asks for, built on the Phase 14 `ErrorAnalyzer` so
research and the live loop classify failures the same way — a research finding
that used a different taxonomy would not be actionable.

Each report answers "when the model failed *this* way, what did it cost?" —
because the count alone does not distinguish a common cheap error from a rare
expensive one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from ai.performance.errors import ErrorAnalysis, ErrorAnalyzer, ErrorClass
from research.metrics import evaluate
from research.models import ResearchObservation, require_forward_only

# Section 20's list, mapped onto the Phase 14 taxonomy.
REPORTS: tuple[str, ...] = (
    "FALSE_BULL", "FALSE_BEAR", "FALSE_NEUTRAL", "HIGH_CONFIDENCE_FAILURE",
    "LOW_CONFIDENCE_FAILURE", "REGIME_FAILURE", "SESSION_FAILURE",
    "LIQUIDITY_FAILURE", "STRUCTURE_FAILURE", "INDICATOR_FAILURE",
)


@dataclass(frozen=True, slots=True)
class ErrorReport:
    kind: str
    count: int
    share: float | None = None
    net_pnl: float | None = None
    average_loss: float | None = None
    worst_loss: float | None = None
    average_confidence: float | None = None
    by_regime: dict[str, int] = field(default_factory=dict)
    by_session: dict[str, int] = field(default_factory=dict)
    examples: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "count": self.count, "share": self.share,
                "net_pnl": self.net_pnl, "average_loss": self.average_loss,
                "worst_loss": self.worst_loss,
                "average_confidence": self.average_confidence,
                "by_regime": dict(self.by_regime), "by_session": dict(self.by_session),
                "examples": list(self.examples)}


class ErrorLab:
    def __init__(self, *, analyzer: ErrorAnalyzer | None = None,
                 minimum_samples: int = 30):
        self.analyzer = analyzer or ErrorAnalyzer()
        self.minimum_samples = int(minimum_samples)

    def classify(self, observations: Sequence[ResearchObservation]
                 ) -> list[tuple[ResearchObservation, ErrorAnalysis]]:
        """Run each observation through the live loop's classifier."""
        pairs: list[tuple[ResearchObservation, ErrorAnalysis]] = []
        for row in require_forward_only(observations):
            pairs.append((row, self.analyzer.classify(_ObservationView(row),
                                                      _OutcomeView(row))))
        return pairs

    def run(self, observations: Sequence[ResearchObservation]) -> dict[str, Any]:
        pairs = self.classify(observations)
        wrong = [(row, analysis) for row, analysis in pairs if not analysis.correct]
        reports: dict[str, ErrorReport] = {}

        for kind in REPORTS:
            matching = [(row, analysis) for row, analysis in wrong
                        if str(analysis.primary) == kind
                        or ErrorClass(kind) in analysis.tags]
            reports[kind] = self._report(kind, matching, len(wrong))

        rows = [row for row, _ in pairs]
        return {
            "observations": len(rows),
            "incorrect": len(wrong),
            "accuracy": ((len(rows) - len(wrong)) / len(rows)) if rows else None,
            "reliable": len(rows) >= self.minimum_samples,
            "reports": {kind: report.as_dict() for kind, report in reports.items()},
            "most_expensive": self._most_expensive(reports),
            "most_common": self._most_common(reports),
            "summary": self.analyzer.summarize([analysis for _, analysis in pairs]),
            "performance_on_errors": evaluate(
                [row for row, _ in wrong], minimum_samples=self.minimum_samples).as_dict(),
        }

    @staticmethod
    def _report(kind: str, matching: Sequence[tuple[ResearchObservation, ErrorAnalysis]],
                total: int) -> ErrorReport:
        if not matching:
            return ErrorReport(kind, 0, 0.0 if total else None)
        returns = [row.net_pnl for row, _ in matching]
        losses = [value for value in returns if value < 0]
        confidences = [row.confidence for row, _ in matching if row.confidence is not None]
        by_regime: dict[str, int] = {}
        by_session: dict[str, int] = {}
        for row, _ in matching:
            if row.regime:
                by_regime[row.regime] = by_regime.get(row.regime, 0) + 1
            if row.session:
                by_session[row.session] = by_session.get(row.session, 0) + 1
        return ErrorReport(
            kind=kind, count=len(matching),
            share=(len(matching) / total) if total else None,
            net_pnl=sum(returns),
            average_loss=(sum(losses) / len(losses)) if losses else None,
            worst_loss=min(returns) if returns else None,
            average_confidence=(sum(confidences) / len(confidences))
            if confidences else None,
            by_regime=by_regime, by_session=by_session,
            examples=tuple(row.observation_id for row, _ in matching[:5]))

    @staticmethod
    def _most_expensive(reports: dict[str, ErrorReport]) -> str | None:
        scored = [(kind, report.net_pnl) for kind, report in reports.items()
                  if report.count and report.net_pnl is not None]
        return min(scored, key=lambda item: item[1])[0] if scored else None

    @staticmethod
    def _most_common(reports: dict[str, ErrorReport]) -> str | None:
        scored = [(kind, report.count) for kind, report in reports.items()
                  if report.count]
        return max(scored, key=lambda item: item[1])[0] if scored else None


class _ObservationView:
    """Adapts a ResearchObservation to what `ErrorAnalyzer` reads."""

    __slots__ = ("_row",)

    def __init__(self, row: ResearchObservation):
        self._row = row

    @property
    def observation_id(self) -> str:
        return self._row.observation_id

    @property
    def direction(self) -> str | None:
        return self._row.predicted

    @property
    def nn_confidence(self) -> float | None:
        return self._row.confidence

    @property
    def market_regime(self) -> str | None:
        return self._row.regime

    @property
    def session(self) -> str | None:
        return self._row.session

    @property
    def timeframe(self) -> str | None:
        return self._row.timeframe

    @property
    def context(self) -> dict[str, Any]:
        return {**dict(self._row.context or {}),
                **{f"{name}_direction": value
                   for name, value in (self._row.signals or {}).items()}}


class _OutcomeView:
    __slots__ = ("_row",)

    def __init__(self, row: ResearchObservation):
        self._row = row

    @property
    def actual_direction(self) -> str | None:
        return self._row.actual

    @property
    def net_hypothetical_pnl(self) -> float:
        return self._row.net_pnl
