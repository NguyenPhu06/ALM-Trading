"""Model error analysis (sections 15 and 16).

When a prediction is wrong, *how* it was wrong is the useful part. A model that
is wrong at 40% confidence is behaving correctly; a model that is wrong at 85%
confidence is broken in a way accuracy alone will never show.

Every wrong prediction gets one primary class plus any contributing tags. The
tags are derived from what the observation itself recorded — the regime it saw,
the structure it read — so a tag is a statement about disagreement, never a claim
that the tagged component caused the failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable, Mapping, Sequence

from config.settings import load_yaml


class ErrorClass(StrEnum):
    FALSE_BULL = "FALSE_BULL"
    FALSE_BEAR = "FALSE_BEAR"
    FALSE_NEUTRAL = "FALSE_NEUTRAL"
    LOW_CONFIDENCE_FAILURE = "LOW_CONFIDENCE_FAILURE"
    HIGH_CONFIDENCE_FAILURE = "HIGH_CONFIDENCE_FAILURE"
    REGIME_FAILURE = "REGIME_FAILURE"
    SESSION_FAILURE = "SESSION_FAILURE"
    LIQUIDITY_FAILURE = "LIQUIDITY_FAILURE"
    STRUCTURE_FAILURE = "STRUCTURE_FAILURE"
    INDICATOR_FAILURE = "INDICATOR_FAILURE"
    UNKNOWN = "UNKNOWN"


BULLISH = {"UP", "BUY", "LONG", "BULL", "STRONG_BULL"}
BEARISH = {"DOWN", "SELL", "SHORT", "BEAR", "STRONG_BEAR"}


def direction_of(value: Any) -> int:
    """+1 bullish, -1 bearish, 0 neutral or unreadable."""
    text = str(value or "").strip().upper()
    if text in BULLISH:
        return 1
    if text in BEARISH:
        return -1
    return 0


@dataclass(frozen=True, slots=True)
class ErrorAnalysis:
    observation_id: str
    correct: bool
    predicted: str
    actual: str
    confidence: float | None
    primary: ErrorClass
    tags: tuple[ErrorClass, ...] = ()
    high_confidence_failure: bool = False
    net_pnl: float | None = None
    regime: str | None = None
    session: str | None = None
    timeframe: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id, "correct": self.correct,
            "predicted": self.predicted, "actual": self.actual,
            "confidence": self.confidence, "primary": str(self.primary),
            "tags": [str(tag) for tag in self.tags],
            "high_confidence_failure": self.high_confidence_failure,
            "net_pnl": self.net_pnl, "regime": self.regime, "session": self.session,
            "timeframe": self.timeframe, **self.context,
        }


class ErrorAnalyzer:
    """Classifies wrong predictions; correct ones are recorded but not tagged."""

    def __init__(self, *, high_confidence_threshold: float | None = None,
                 weak_sessions: Iterable[str] = ()):
        config = load_yaml().get("phase_14", {})
        self.high_confidence_threshold = float(
            high_confidence_threshold if high_confidence_threshold is not None
            else config.get("high_confidence_threshold", 0.75))
        self.weak_sessions = {str(name).upper() for name in weak_sessions}

    # -------------------------------------------------------------- classify
    def classify(self, observation: Any, outcome: Any) -> ErrorAnalysis:
        observation_id = str(_read(observation, "observation_id") or "")
        predicted = str(_read(observation, "direction") or "WAIT").upper()
        actual = str(_read(outcome, "actual_direction") or "").upper()
        confidence = _number(_read(observation, "nn_confidence"))
        net = _number(_read(outcome, "net_hypothetical_pnl"))
        regime = _read(observation, "market_regime")
        session = _read(observation, "session")
        timeframe = _read(observation, "timeframe")

        predicted_direction = direction_of(predicted)
        actual_direction = direction_of(actual)
        correct = predicted_direction == actual_direction and predicted_direction != 0

        if correct:
            return ErrorAnalysis(observation_id, True, predicted, actual, confidence,
                                 ErrorClass.UNKNOWN, (), False, net,
                                 _text(regime), _text(session), _text(timeframe),
                                 context={"note": "CORRECT_PREDICTION"})

        primary = self._primary(predicted_direction, actual_direction)
        tags: list[ErrorClass] = []

        high_confidence = (confidence is not None
                           and confidence >= self.high_confidence_threshold)
        tags.append(ErrorClass.HIGH_CONFIDENCE_FAILURE if high_confidence
                    else ErrorClass.LOW_CONFIDENCE_FAILURE)

        context = _mapping(_read(observation, "context"))
        if predicted_direction and direction_of(regime) == -predicted_direction:
            tags.append(ErrorClass.REGIME_FAILURE)
        if session and _text(session).upper() in self.weak_sessions:
            tags.append(ErrorClass.SESSION_FAILURE)
        for key, tag in (("structure_direction", ErrorClass.STRUCTURE_FAILURE),
                         ("indicator_direction", ErrorClass.INDICATOR_FAILURE),
                         ("liquidity_direction", ErrorClass.LIQUIDITY_FAILURE)):
            if predicted_direction and direction_of(context.get(key)) == -predicted_direction:
                tags.append(tag)

        return ErrorAnalysis(
            observation_id, False, predicted, actual, confidence, primary, tuple(tags),
            high_confidence, net, _text(regime), _text(session), _text(timeframe),
            context={"threshold": self.high_confidence_threshold})

    @staticmethod
    def _primary(predicted: int, actual: int) -> ErrorClass:
        if predicted > 0:
            return ErrorClass.FALSE_BULL
        if predicted < 0:
            return ErrorClass.FALSE_BEAR
        if actual != 0:
            return ErrorClass.FALSE_NEUTRAL
        return ErrorClass.UNKNOWN

    # --------------------------------------------------------------- summary
    def analyze(self, pairs: Sequence[tuple[Any, Any]]) -> list[ErrorAnalysis]:
        return [self.classify(observation, outcome) for observation, outcome in pairs]

    def summarize(self, analyses: Sequence[ErrorAnalysis]) -> dict[str, Any]:
        wrong = [item for item in analyses if not item.correct]
        counts: dict[str, int] = {}
        for item in wrong:
            counts[str(item.primary)] = counts.get(str(item.primary), 0) + 1
            for tag in item.tags:
                counts[str(tag)] = counts.get(str(tag), 0) + 1

        high = [item for item in wrong if item.high_confidence_failure]
        by_regime: dict[str, int] = {}
        by_session: dict[str, int] = {}
        for item in wrong:
            if item.regime:
                by_regime[item.regime] = by_regime.get(item.regime, 0) + 1
            if item.session:
                by_session[item.session] = by_session.get(item.session, 0) + 1

        total = len(analyses)
        return {
            "samples": total, "correct": total - len(wrong), "incorrect": len(wrong),
            "accuracy": (total - len(wrong)) / total if total else None,
            "by_class": counts, "by_regime": by_regime, "by_session": by_session,
            "high_confidence_failures": len(high),
            "high_confidence_failure_rate": len(high) / len(wrong) if wrong else 0.0,
            "high_confidence_threshold": self.high_confidence_threshold,
            "worst": [item.as_dict() for item in
                      sorted(high, key=lambda entry: entry.confidence or 0.0,
                             reverse=True)[:10]],
        }


def _read(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return str(value) if value is not None else None
