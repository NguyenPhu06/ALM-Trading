"""Where the model works, where it fails, and where its confidence lies.

Sections 17, 18 and 19. The same machinery runs over three dimensions, because
the mistake it exists to prevent is identical in all three: assuming that good
aggregate performance means good performance everywhere.

A model that performs well on M5 has said nothing about H1. A model that is
profitable overall may be carried entirely by LONDON while losing in ASIA. And a
segment where confidence is high but accuracy is not is worse than a segment
where the model is simply weak — it is a model that does not know it is wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Sequence

from ai.performance.rolling import PerformanceEntry, calibration_report
from config.settings import load_yaml

# The vocabularies this system actually produces. `CUSTOM` collects anything a
# provider hands back that is not one of the known session names.
REGIME_SEGMENTS = ("STRONG_BULL", "BULL", "RANGE", "BEAR", "STRONG_BEAR", "UNKNOWN")
SESSION_SEGMENTS = ("ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP",
                    "OFF_SESSION", "CUSTOM")
TIMEFRAME_SEGMENTS = ("D1", "H4", "H1", "M30", "M15", "M5")


class SegmentVerdict(StrEnum):
    WORKS = "WORKS"
    FAILS = "FAILS"
    MISLEADING_CONFIDENCE = "MISLEADING_CONFIDENCE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class SegmentLearning:
    dimension: str
    segment: str
    samples: int
    reliable: bool
    verdict: SegmentVerdict
    accuracy: float | None = None
    expectancy: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    net_pnl: float | None = None
    max_drawdown: float | None = None
    average_mae: float | None = None
    average_mfe: float | None = None
    average_spread: float | None = None
    average_confidence: float | None = None
    calibration_gap: float | None = None
    overconfident: bool = False
    calibration: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "segment": self.segment,
                "samples": self.samples, "reliable": self.reliable,
                "verdict": str(self.verdict), "accuracy": self.accuracy,
                "expectancy": self.expectancy, "win_rate": self.win_rate,
                "profit_factor": self.profit_factor, "net_pnl": self.net_pnl,
                "max_drawdown": self.max_drawdown, "average_mae": self.average_mae,
                "average_mfe": self.average_mfe, "average_spread": self.average_spread,
                "average_confidence": self.average_confidence,
                "calibration_gap": self.calibration_gap,
                "overconfident": self.overconfident,
                "calibration": dict(self.calibration)}


@dataclass(frozen=True, slots=True)
class SegmentLearningReport:
    dimension: str
    segments: dict[str, SegmentLearning]
    minimum_samples: int

    def _named(self, verdict: SegmentVerdict) -> tuple[str, ...]:
        return tuple(name for name, item in sorted(self.segments.items())
                     if item.verdict is verdict)

    @property
    def works(self) -> tuple[str, ...]:
        return self._named(SegmentVerdict.WORKS)

    @property
    def fails(self) -> tuple[str, ...]:
        return self._named(SegmentVerdict.FAILS)

    @property
    def misleading(self) -> tuple[str, ...]:
        return self._named(SegmentVerdict.MISLEADING_CONFIDENCE)

    @property
    def overconfident(self) -> tuple[str, ...]:
        """Reported separately from the verdict.

        A losing segment's verdict is FAILS — losing money is the headline — but
        the model may *also* have been sure about it. Folding that into the
        verdict would hide one of the two facts, so both are reported.
        """
        return tuple(name for name, item in sorted(self.segments.items())
                     if item.reliable and item.overconfident)

    @property
    def reliable_segments(self) -> tuple[str, ...]:
        return tuple(name for name, item in sorted(self.segments.items()) if item.reliable)

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "minimum_samples": self.minimum_samples,
                "works": list(self.works), "fails": list(self.fails),
                "misleading_confidence": list(self.misleading),
                "overconfident": list(self.overconfident),
                "reliable_segments": list(self.reliable_segments),
                "segments": {name: item.as_dict()
                             for name, item in sorted(self.segments.items())}}


class ForwardSegmentLearner:
    """Segments resolved forward observations and judges each segment separately."""

    def __init__(self, *, minimum_samples: int | None = None,
                 calibration_gap_threshold: float | None = None):
        config = load_yaml().get("phase_14", {})
        self.minimum_samples = int(minimum_samples if minimum_samples is not None
                                   else config.get("segment_minimum_samples", 30))
        self.calibration_gap_threshold = float(
            calibration_gap_threshold if calibration_gap_threshold is not None
            else config.get("calibration_gap_threshold", 0.20))

    # -------------------------------------------------------------- dimensions
    def by_regime(self, entries: Sequence[PerformanceEntry]) -> SegmentLearningReport:
        return self.evaluate(entries, "regime", REGIME_SEGMENTS)

    def by_session(self, entries: Sequence[PerformanceEntry]) -> SegmentLearningReport:
        return self.evaluate(entries, "session", SESSION_SEGMENTS)

    def by_timeframe(self, entries: Sequence[PerformanceEntry]) -> SegmentLearningReport:
        return self.evaluate(entries, "timeframe", TIMEFRAME_SEGMENTS)

    def all_dimensions(self, entries: Sequence[PerformanceEntry]) -> dict[str, Any]:
        return {"regime": self.by_regime(entries).as_dict(),
                "session": self.by_session(entries).as_dict(),
                "timeframe": self.by_timeframe(entries).as_dict()}

    # ---------------------------------------------------------------- evaluate
    def evaluate(self, entries: Sequence[PerformanceEntry], dimension: str,
                 known: Sequence[str] = ()) -> SegmentLearningReport:
        grouped: dict[str, list[PerformanceEntry]] = {name: [] for name in known}
        for entry in entries:
            name = _segment_name(getattr(entry, dimension, None), known)
            grouped.setdefault(name, []).append(entry)

        segments = {name: self._metrics(dimension, name, rows)
                    for name, rows in grouped.items()}
        return SegmentLearningReport(dimension, segments, self.minimum_samples)

    def _metrics(self, dimension: str, segment: str,
                 rows: Sequence[PerformanceEntry]) -> SegmentLearning:
        if not rows:
            return SegmentLearning(dimension, segment, 0, False,
                                   SegmentVerdict.INSUFFICIENT_DATA)

        returns = [entry.net_pnl for entry in rows]
        wins = [value for value in returns if value > 0]
        losses = [value for value in returns if value < 0]
        gross_loss = abs(sum(losses))
        judged = [entry for entry in rows if entry.correct is not None]
        confidences = [entry.confidence for entry in rows if entry.confidence is not None]
        maes = [entry.mae for entry in rows if entry.mae is not None]
        mfes = [entry.mfe for entry in rows if entry.mfe is not None]

        accuracy = (sum(1 for entry in judged if entry.correct) / len(judged)
                    if judged else None)
        average_confidence = (sum(confidences) / len(confidences)) if confidences else None
        gap = (average_confidence - accuracy
               if average_confidence is not None and accuracy is not None else None)
        expectancy = sum(returns) / len(returns)
        reliable = len(rows) >= self.minimum_samples

        overconfident = gap is not None and gap >= self.calibration_gap_threshold
        return SegmentLearning(
            dimension=dimension, segment=segment, samples=len(rows), reliable=reliable,
            verdict=self._verdict(reliable, expectancy, accuracy, gap),
            overconfident=overconfident,
            accuracy=accuracy, expectancy=expectancy,
            win_rate=len(wins) / len(rows),
            profit_factor=(sum(wins) / gross_loss) if gross_loss else None,
            net_pnl=sum(returns), max_drawdown=_max_drawdown(returns),
            average_mae=(sum(maes) / len(maes)) if maes else None,
            average_mfe=(sum(mfes) / len(mfes)) if mfes else None,
            average_spread=_average_spread(rows), average_confidence=average_confidence,
            calibration_gap=gap, calibration=calibration_report(judged))

    def _verdict(self, reliable: bool, expectancy: float, accuracy: float | None,
                 gap: float | None) -> SegmentVerdict:
        if not reliable:
            return SegmentVerdict.INSUFFICIENT_DATA
        # Losing money is the headline: a segment with negative expectancy FAILS
        # even when the model was also overconfident there. The `overconfident`
        # flag carries that second fact so neither one hides the other.
        if expectancy <= 0:
            return SegmentVerdict.FAILS
        # MISLEADING_CONFIDENCE is reserved for segments that do NOT look like
        # failures — profitable, but the model does not know why.
        if gap is not None and gap >= self.calibration_gap_threshold:
            return SegmentVerdict.MISLEADING_CONFIDENCE
        if accuracy is None or accuracy > 0.5:
            return SegmentVerdict.WORKS
        return SegmentVerdict.FAILS


def _segment_name(value: Any, known: Sequence[str]) -> str:
    text = str(value or "UNKNOWN").upper()
    if not known:
        return text
    if text in known:
        return text
    return "CUSTOM" if "CUSTOM" in known else "UNKNOWN"


def _average_spread(rows: Sequence[PerformanceEntry]) -> float | None:
    spreads = [entry.spread for entry in rows if entry.spread is not None]
    return (sum(spreads) / len(spreads)) if spreads else None


def _max_drawdown(returns: Sequence[float]) -> float | None:
    if not returns:
        return None
    equity = peak = worst = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)
