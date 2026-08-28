"""The explicit training job (sections 10 and 12).

Section 10 is the reason this file exists as a separate entry point:

    Do NOT train the model after every observation.
    Do NOT train inside the market cycle.
    Do NOT perform uncontrolled online learning.

`TrainingJob` is the only sanctioned way to fit a model. It holds no broker
client, no execution guard and no kill switch, and it changes no setting. Import
graph tests assert that the observation loop cannot reach it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ai.dataset.builder import BuiltDataset
from ai.model_registry.records import ModelTask
from ai.models.multitask import MultiTaskConfig
from ai.training.forward_trainer import ForwardTrainer, TrainingDisabled, TrainingReport
from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


class OnlineLearningRefused(RuntimeError):
    """Raised when something tries to fit a model outside the explicit job."""


@dataclass(frozen=True, slots=True)
class JobResult:
    started_at: datetime
    finished_at: datetime
    report: TrainingReport | None
    error: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.report is not None

    # Constants, asserted by the Phase 14 safety tests.
    @property
    def orders_sent(self) -> int:
        return 0

    @property
    def promoted(self) -> bool:
        return False

    def as_dict(self) -> dict[str, Any]:
        return {"started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat(),
                "duration_seconds": (self.finished_at - self.started_at).total_seconds(),
                "ok": self.ok, "error": self.error, "orders_sent": 0, "promoted": False,
                "model_id": self.report.model_id if self.report else None,
                **self.context}


class TrainingJob:
    """Fits one challenger from one prepared dataset. Nothing else."""

    def __init__(self, settings: Settings | None = None, *,
                 config: MultiTaskConfig | None = None,
                 trainer: ForwardTrainer | None = None):
        self.settings = settings or get_settings()
        if self.settings.ai_online_learning_enabled:
            # Unreachable while the startup validator holds; kept as defence in depth.
            raise OnlineLearningRefused(
                "AI_ONLINE_LEARNING_ENABLED must be false: training is an explicit job")
        self.config = config or MultiTaskConfig()
        self.trainer = trainer or ForwardTrainer(self.settings, config=self.config)

    def run(self, dataset: BuiltDataset, *, task: ModelTask | None = None,
            model_version: str | None = None) -> JobResult:
        """Train, and report. Never raises for a training failure."""
        started = datetime.now(timezone.utc)
        if not self.settings.ai_training_enabled:
            return JobResult(started, datetime.now(timezone.utc), None,
                             "AI_TRAINING_ENABLED is false",
                             context={"skipped": True})
        try:
            report = self.trainer.train(dataset, task=task, model_version=model_version)
        except TrainingDisabled as error:
            logger.warning("training refused: %s", error)
            return JobResult(started, datetime.now(timezone.utc), None, str(error),
                             context={"refused": True})
        except Exception as error:
            logger.exception("training job failed")
            return JobResult(started, datetime.now(timezone.utc), None,
                             f"{type(error).__name__}: {error}")
        return JobResult(started, datetime.now(timezone.utc), report,
                         context={"edge_verdict": report.record.edge_verdict,
                                  "beats_all_baselines": report.beats_all_baselines,
                                  "state": str(report.record.state)})
