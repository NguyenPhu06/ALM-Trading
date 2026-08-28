"""Controlled retraining policy and the human approval gate.

Triggers only ever produce a *request*. A request is not a training run, and a
training run is not a promotion. The chain is deliberately three separate steps
with a human at the end:

    trigger -> RetrainingRequest -> (explicit job) -> new model version
        -> compare -> HUMAN APPROVAL -> promote

Retraining always creates a new model version. The champion is never overwritten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from config.settings import Settings, get_settings, load_yaml


class RetrainingTrigger(StrEnum):
    SCHEDULED = "SCHEDULED"
    NEW_OBSERVATIONS = "NEW_OBSERVATIONS"
    PERFORMANCE_DEGRADATION = "PERFORMANCE_DEGRADATION"
    FEATURE_DRIFT = "FEATURE_DRIFT"
    MANUAL = "MANUAL"


class RequestState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class RetrainingRequest:
    request_id: str
    triggers: tuple[RetrainingTrigger, ...]
    reasons: tuple[str, ...]
    state: RequestState = RequestState.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_by: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def triggered(self) -> bool:
        return bool(self.triggers)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "triggers": [str(item) for item in self.triggers],
            "reasons": list(self.reasons), "state": str(self.state),
            "created_at": self.created_at, "approved_by": self.approved_by,
            # Stated explicitly so nothing downstream can misread a request.
            "auto_trains": False, "auto_promotes": False,
            **self.context,
        }


class RetrainingPolicy:
    """Decides whether retraining is *warranted*. It never trains anything."""

    def __init__(self, settings: Settings | None = None, *,
                 minimum_new_observations: int | None = None,
                 scheduled_interval_days: float | None = None,
                 performance_degradation: float | None = None):
        self.settings = settings or get_settings()
        config = load_yaml().get("phase_13", {}).get("retraining", {})
        self.minimum_new_observations = int(
            minimum_new_observations if minimum_new_observations is not None
            else config.get("minimum_new_observations", 500))
        self.scheduled_interval = timedelta(days=float(
            scheduled_interval_days if scheduled_interval_days is not None
            else config.get("scheduled_interval_days", 7)))
        self.performance_degradation = float(
            performance_degradation if performance_degradation is not None
            else config.get("performance_degradation", 0.10))

    def evaluate(self, *, new_observations: int = 0,
                 last_training: datetime | None = None,
                 baseline_score: float | None = None, current_score: float | None = None,
                 drift_flagged: bool = False, manual: bool = False,
                 now: datetime | None = None) -> RetrainingRequest:
        moment = now or datetime.now(timezone.utc)
        triggers: list[RetrainingTrigger] = []
        reasons: list[str] = []

        if manual:
            triggers.append(RetrainingTrigger.MANUAL)
            reasons.append("MANUAL_REQUEST")

        if new_observations >= self.minimum_new_observations:
            triggers.append(RetrainingTrigger.NEW_OBSERVATIONS)
            reasons.append(f"NEW_OBSERVATIONS_{new_observations}")

        if last_training is not None and moment - last_training >= self.scheduled_interval:
            triggers.append(RetrainingTrigger.SCHEDULED)
            reasons.append(f"LAST_TRAINING_{(moment - last_training).days}_DAYS_AGO")

        if baseline_score is not None and current_score is not None:
            drop = baseline_score - current_score
            if drop >= self.performance_degradation:
                triggers.append(RetrainingTrigger.PERFORMANCE_DEGRADATION)
                reasons.append(f"SCORE_DROP_{drop:.4f}")

        if drift_flagged:
            triggers.append(RetrainingTrigger.FEATURE_DRIFT)
            reasons.append("DRIFT_FLAGGED")

        return RetrainingRequest(
            uuid4().hex, tuple(dict.fromkeys(triggers)), tuple(reasons),
            created_at=moment,
            context={"new_observations": new_observations,
                     "training_enabled": self.settings.ai_training_enabled})

    def approve(self, request: RetrainingRequest, *, approved_by: str,
                reason: str) -> RetrainingRequest:
        from dataclasses import replace

        if not str(approved_by).strip():
            raise ValueError("approving a retraining request requires a named human")
        if not str(reason).strip():
            raise ValueError("approving a retraining request requires a reason")
        return replace(request, state=RequestState.APPROVED, approved_by=approved_by,
                       reasons=(*request.reasons, f"APPROVED:{reason}"))

    def reject(self, request: RetrainingRequest, *, reason: str) -> RetrainingRequest:
        from dataclasses import replace

        return replace(request, state=RequestState.REJECTED,
                       reasons=(*request.reasons, f"REJECTED:{reason}"))

    @staticmethod
    def next_version(current_version: str | None) -> str:
        """Retraining always mints a new version; it never overwrites one."""
        if not current_version:
            return "multitask_mlp.v1"
        head, _, tail = current_version.rpartition(".v")
        if head and tail.isdigit():
            return f"{head}.v{int(tail) + 1}"
        return f"{current_version}.v2"
