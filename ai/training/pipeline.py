"""The ten-step training pipeline (section 12).

    1. load dataset          6. train challenger
    2. validate dataset      7. evaluate challenger
    3. check leakage         8. compare with champion
    4. split chronologically 9. generate report
    5. fit preprocessing    10. register model
       (TRAIN only)

Step 10 registers. There is no step 11: `promoted` is a constant False, and the
only way past it is `POST /ai/models/{model_id}/approve` with a named human.

Steps 1-5 are performed by `DatasetBuilder`, which builds, checks and splits in
one pass. The pipeline records each of them separately anyway, so a failure
reports *which* stage refused rather than a single opaque "dataset invalid".
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence

from ai.dataset.builder import BuiltDataset, DatasetBuilder
from ai.edge.evidence import EvidenceSource
from ai.model_registry.records import ModelRecord, ModelTask
from ai.model_registry.registry import ModelRegistry
from ai.training.evaluation import ChallengerEvaluation, ChallengerEvaluator
from ai.training.train import JobResult, TrainingJob
from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class PipelineStep(StrEnum):
    LOAD = "LOAD"
    VALIDATE = "VALIDATE"
    LEAKAGE = "LEAKAGE"
    SPLIT = "SPLIT"
    PREPROCESS = "PREPROCESS"
    TRAIN = "TRAIN"
    EVALUATE = "EVALUATE"
    COMPARE = "COMPARE"
    REPORT = "REPORT"
    REGISTER = "REGISTER"


@dataclass(frozen=True, slots=True)
class StepResult:
    step: PipelineStep
    ok: bool
    detail: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"step": str(self.step), "ok": self.ok, "detail": self.detail,
                **self.data}


@dataclass(frozen=True, slots=True)
class PipelineReport:
    steps: tuple[StepResult, ...]
    dataset: BuiltDataset | None = None
    job: JobResult | None = None
    evaluation: ChallengerEvaluation | None = None
    record: ModelRecord | None = None
    registered: bool = False
    evidence: EvidenceSource = EvidenceSource.FORWARD_OBSERVATION

    @property
    def ok(self) -> bool:
        return all(step.ok for step in self.steps)

    @property
    def failed_step(self) -> PipelineStep | None:
        for step in self.steps:
            if not step.ok:
                return step.step
        return None

    # Constants. The pipeline registers; it never promotes and never trades.
    @property
    def promoted(self) -> bool:
        return False

    @property
    def orders_sent(self) -> int:
        return 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failed_step": str(self.failed_step) if self.failed_step else None,
            "steps": [step.as_dict() for step in self.steps],
            "dataset_id": self.dataset.dataset_id if self.dataset else None,
            "model_id": self.record.model_id if self.record else None,
            "state": str(self.record.state) if self.record else None,
            "evaluation": self.evaluation.as_dict() if self.evaluation else None,
            "job": self.job.as_dict() if self.job else None,
            "registered": self.registered, "promoted": False, "orders_sent": 0,
            "requires_human_approval": True, "evidence": str(self.evidence),
        }


class TrainingPipeline:
    def __init__(self, settings: Settings | None = None, *,
                 builder: DatasetBuilder | None = None, job: TrainingJob | None = None,
                 evaluator: ChallengerEvaluator | None = None,
                 registry: ModelRegistry | None = None):
        self.settings = settings or get_settings()
        self.builder = builder or DatasetBuilder()
        self.job = job or TrainingJob(self.settings)
        self.evaluator = evaluator or ChallengerEvaluator()
        self.registry = registry

    # -------------------------------------------------------------------- run
    def run(self, observations: Sequence[Mapping[str, Any]],
            future_candles: Sequence[Mapping[str, Any]], *, horizon: str | None = None,
            now: datetime | None = None, symbol: str | None = None,
            timeframe: str = "M5", task: ModelTask | None = None,
            champion: ModelRecord | None = None) -> PipelineReport:
        moment = now or datetime.now(timezone.utc)
        steps: list[StepResult] = []

        steps.append(StepResult(PipelineStep.LOAD, bool(observations),
                                None if observations else "NO_OBSERVATIONS",
                                {"observations": len(observations),
                                 "future_candles": len(future_candles)}))
        if not observations:
            return PipelineReport(tuple(steps))

        dataset = self.builder.build(observations, future_candles, horizon=horizon,
                                     now=moment, symbol=symbol, timeframe=timeframe)

        steps.append(self._validate(dataset))
        steps.append(self._leakage(dataset))
        steps.append(self._split(dataset))
        steps.append(self._preprocess(dataset))
        if not all(step.ok for step in steps):
            return PipelineReport(tuple(steps), dataset)

        job = self.job.run(dataset, task=task)
        steps.append(StepResult(PipelineStep.TRAIN, job.ok, job.error,
                                {"model_id": job.report.model_id if job.report else None,
                                 "duration_seconds": (job.finished_at
                                                      - job.started_at).total_seconds()}))
        if not job.ok:
            return PipelineReport(tuple(steps), dataset, job)

        report = job.report
        evaluation = self.evaluator.evaluate(report, champion=champion)
        steps.append(StepResult(PipelineStep.EVALUATE, True, str(evaluation.verdict),
                                {"beats_baselines": evaluation.beats_baselines,
                                 "reasons": list(evaluation.reasons)}))
        steps.append(StepResult(PipelineStep.COMPARE, True,
                                "NO_INCUMBENT_CHAMPION" if champion is None else None,
                                {"beats_champion": evaluation.beats_champion,
                                 "comparison": evaluation.comparison}))
        steps.append(StepResult(PipelineStep.REPORT, True, None,
                                {"summary": _summary(report, evaluation)}))

        registered = False
        detail = "NO_REGISTRY_CONFIGURED"
        if self.registry is not None:
            try:
                self.registry.register(report.record)
                registered = True
                detail = None
            except Exception as error:
                logger.exception("model registration failed")
                detail = f"{type(error).__name__}: {error}"
        steps.append(StepResult(PipelineStep.REGISTER, self.registry is None or registered,
                                detail, {"registered": registered,
                                         # Registration is not promotion.
                                         "state": str(report.record.state),
                                         "promoted": False}))
        return PipelineReport(tuple(steps), dataset, job, evaluation, report.record,
                              registered)

    # ------------------------------------------------------------------ steps
    @staticmethod
    def _validate(dataset: BuiltDataset) -> StepResult:
        codes = tuple(dataset.quality.codes)
        return StepResult(PipelineStep.VALIDATE, dataset.quality.ok,
                          ", ".join(codes) or None,
                          {"rows": len(dataset.train) + len(dataset.validation)
                           + len(dataset.test), "refusals": dict(dataset.refusals),
                           "codes": list(codes)})

    @staticmethod
    def _leakage(dataset: BuiltDataset) -> StepResult:
        leaks = [code for code in dataset.quality.codes if "LEAK" in code or "FUTURE" in code]
        return StepResult(PipelineStep.LEAKAGE, not leaks,
                          ", ".join(leaks) or None, {"leakage_codes": leaks})

    @staticmethod
    def _split(dataset: BuiltDataset) -> StepResult:
        ok = bool(len(dataset.train) and len(dataset.validation) and len(dataset.test))
        chronological = True
        if ok:
            last_train = max(row.timestamp for row in dataset.train.rows)
            first_test = min(row.timestamp for row in dataset.test.rows)
            chronological = last_train < first_test
        return StepResult(PipelineStep.SPLIT, ok and chronological,
                          None if ok and chronological else "SPLIT_NOT_CHRONOLOGICAL",
                          {"train": len(dataset.train), "validation": len(dataset.validation),
                           "test": len(dataset.test), "chronological": chronological})

    @staticmethod
    def _preprocess(dataset: BuiltDataset) -> StepResult:
        # The scaler is fitted on TRAIN only; ScalerState records which split it saw.
        fitted_on = getattr(dataset.scaler, "fitted_split", "")
        ok = str(fitted_on).upper() == "TRAIN" and bool(dataset.scaler.means)
        return StepResult(PipelineStep.PREPROCESS, ok,
                          None if ok else f"SCALER_FITTED_ON_{fitted_on}",
                          {"fitted_on": str(fitted_on),
                           "features": len(dataset.feature_names)})


def _summary(report: Any, evaluation: ChallengerEvaluation) -> dict[str, Any]:
    record = report.record
    return {"model_id": record.model_id, "model_version": record.model_version,
            "dataset_version": record.training_dataset_version,
            "feature_version": record.feature_version,
            "edge_verdict": record.edge_verdict,
            "beats_all_baselines": report.beats_all_baselines,
            "verdict": str(evaluation.verdict),
            "test_metrics": dict(record.test_metrics or {}),
            "walk_forward": dict(record.walk_forward_metrics or {}),
            "promoted": False}
