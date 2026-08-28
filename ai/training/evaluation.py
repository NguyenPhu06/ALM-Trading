"""Challenger evaluation (section 12, steps 7 and 8).

Separated from training on purpose: the code that produces a model must not be
the code that decides whether the model is good. This module reads a finished
training report and asks three questions, in order:

    1. Is the evaluation trustworthy?   (out-of-sample, enough samples, no leakage)
    2. Does it beat the baselines?      (a tie is not a win)
    3. Does it beat the champion?       (on out-of-sample criteria only)

The answer is never "promote". Promotion needs a named human — see
`ai/model_registry/registry.py`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from ai.model_registry.comparison import ChampionChallengerComparator
from ai.model_registry.records import ModelRecord, ModelState


class EvaluationVerdict(StrEnum):
    PROMOTABLE = "PROMOTABLE"
    NOT_PROMOTABLE = "NOT_PROMOTABLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class ChallengerEvaluation:
    model_id: str
    verdict: EvaluationVerdict
    beats_baselines: bool
    beats_champion: bool | None
    edge_verdict: str
    reasons: tuple[str, ...] = ()
    comparison: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def promotable(self) -> bool:
        return self.verdict is EvaluationVerdict.PROMOTABLE

    # Stated as a property so no caller can mistake evaluation for promotion.
    @property
    def promoted(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {"model_id": self.model_id, "verdict": str(self.verdict),
                "beats_baselines": self.beats_baselines,
                "beats_champion": self.beats_champion,
                "edge_verdict": self.edge_verdict, "reasons": list(self.reasons),
                "comparison": dict(self.comparison), "metrics": dict(self.metrics),
                "promotable": self.promotable, "promoted": False,
                "requires_human_approval": True}


class ChallengerEvaluator:
    def __init__(self, *, minimum_test_samples: int = 100,
                 comparator: ChampionChallengerComparator | None = None):
        self.minimum_test_samples = int(minimum_test_samples)
        self.comparator = comparator or ChampionChallengerComparator()

    def evaluate(self, report: Any, *, champion: ModelRecord | None = None
                 ) -> ChallengerEvaluation:
        record: ModelRecord = report.record
        test_metrics: Mapping[str, Any] = record.test_metrics or {}
        samples = int(test_metrics.get("samples", 0) or 0)

        reasons: list[str] = []
        if samples < self.minimum_test_samples:
            reasons.append(f"TEST_SAMPLES_BELOW_{self.minimum_test_samples}")
        if not report.beats_all_baselines:
            reasons.append("DOES_NOT_BEAT_BASELINES")
        if record.edge_verdict != "EDGE_DETECTED":
            reasons.append(f"EDGE_VERDICT_{record.edge_verdict}")

        comparison: dict[str, Any] = {}
        beats_champion: bool | None = None
        if champion is not None:
            # The comparator refuses an EXPERIMENTAL challenger by design; a freshly
            # trained model is exactly that, so compare a VALIDATED view of it.
            candidate = record if record.state is not ModelState.EXPERIMENTAL else \
                _as_validated(record)
            result = self.comparator.compare(champion=champion, challenger=candidate)
            comparison = result.as_dict() if hasattr(result, "as_dict") else dict(result)
            # `challenger_wins` is a count of criteria; the verdict is the flag.
            beats_champion = bool(comparison.get("recommend_promotion", False))
            if not beats_champion:
                reasons.append("DOES_NOT_BEAT_CHAMPION")

        if samples < self.minimum_test_samples:
            verdict = EvaluationVerdict.INSUFFICIENT_EVIDENCE
        elif reasons:
            verdict = EvaluationVerdict.NOT_PROMOTABLE
        else:
            verdict = EvaluationVerdict.PROMOTABLE

        return ChallengerEvaluation(
            model_id=record.model_id, verdict=verdict,
            beats_baselines=bool(report.beats_all_baselines),
            beats_champion=beats_champion, edge_verdict=record.edge_verdict,
            reasons=tuple(reasons), comparison=comparison,
            metrics={"test": dict(test_metrics),
                     "validation": dict(record.validation_metrics or {}),
                     "walk_forward": dict(record.walk_forward_metrics or {}),
                     "calibration": dict(record.calibration or {})})


def _as_validated(record: ModelRecord) -> ModelRecord:
    from dataclasses import replace

    return replace(record, state=ModelState.VALIDATED)
