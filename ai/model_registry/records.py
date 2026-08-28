"""Model records and the lifecycle they move through.

    EXPERIMENTAL -> VALIDATED -> CANDIDATE -> CHAMPION
                                     |
                                  REJECTED
    CHAMPION -> RETIRED

Exactly one CHAMPION per (task, symbol, timeframe). Promotion is never automatic:
`ModelRegistry.promote` requires an approval token carrying a human approver.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ModelState(StrEnum):
    EXPERIMENTAL = "EXPERIMENTAL"
    VALIDATED = "VALIDATED"
    CANDIDATE = "CANDIDATE"
    CHAMPION = "CHAMPION"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


# The only transitions the registry will perform.
ALLOWED_TRANSITIONS: dict[ModelState, set[ModelState]] = {
    ModelState.EXPERIMENTAL: {ModelState.VALIDATED, ModelState.REJECTED},
    ModelState.VALIDATED: {ModelState.CANDIDATE, ModelState.REJECTED},
    ModelState.CANDIDATE: {ModelState.CHAMPION, ModelState.REJECTED},
    ModelState.CHAMPION: {ModelState.RETIRED},
    ModelState.REJECTED: set(),
    ModelState.RETIRED: set(),
}


class InvalidModelTransition(ValueError):
    """Raised when a transition outside ALLOWED_TRANSITIONS is attempted."""


@dataclass(frozen=True, slots=True)
class ModelTask:
    """Only one champion may exist per task key."""

    task: str = "direction"
    symbol: str = "EURUSD"
    timeframe: str = "M5"

    @property
    def key(self) -> str:
        return f"{self.task}:{self.symbol}:{self.timeframe}"

    def as_dict(self) -> dict[str, Any]:
        return {"task": self.task, "symbol": self.symbol, "timeframe": self.timeframe,
                "key": self.key}


@dataclass(frozen=True, slots=True)
class ApprovalToken:
    """Evidence that a human approved this promotion (section 27)."""

    approved_by: str
    reason: str
    approved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not str(self.approved_by).strip():
            raise ValueError("promotion requires a named human approver")
        if not str(self.reason).strip():
            raise ValueError("promotion requires a stated reason")

    def as_dict(self) -> dict[str, Any]:
        return {"approved_by": self.approved_by, "reason": self.reason,
                "approved_at": self.approved_at}


@dataclass(frozen=True, slots=True)
class ModelRecord:
    model_id: str
    model_version: str
    task: ModelTask
    feature_version: str
    label_version: str
    training_dataset_version: str
    preprocessing_version: str
    state: ModelState = ModelState.EXPERIMENTAL
    training_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    validation_metrics: dict[str, Any] = field(default_factory=dict)
    test_metrics: dict[str, Any] = field(default_factory=dict)
    walk_forward_metrics: dict[str, Any] = field(default_factory=dict)
    regime_metrics: dict[str, Any] = field(default_factory=dict)
    session_metrics: dict[str, Any] = field(default_factory=dict)
    baseline_comparison: dict[str, Any] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    explainability: dict[str, Any] = field(default_factory=dict)
    edge_verdict: str = "NO_EDGE"
    artifact_path: str | None = None
    approval: ApprovalToken | None = None
    notes: tuple[str, ...] = ()

    @property
    def is_champion(self) -> bool:
        return self.state is ModelState.CHAMPION

    @property
    def promotable(self) -> bool:
        return self.state is ModelState.CANDIDATE

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id, "model_version": self.model_version,
            "task": self.task.as_dict(), "feature_version": self.feature_version,
            "label_version": self.label_version,
            "training_dataset_version": self.training_dataset_version,
            "preprocessing_version": self.preprocessing_version, "state": str(self.state),
            "training_timestamp": self.training_timestamp,
            "validation_metrics": dict(self.validation_metrics),
            "test_metrics": dict(self.test_metrics),
            "walk_forward_metrics": dict(self.walk_forward_metrics),
            "regime_metrics": dict(self.regime_metrics),
            "session_metrics": dict(self.session_metrics),
            "baseline_comparison": dict(self.baseline_comparison),
            "calibration": dict(self.calibration),
            "explainability": dict(self.explainability),
            "edge_verdict": self.edge_verdict, "artifact_path": self.artifact_path,
            "approval": self.approval.as_dict() if self.approval else None,
            "notes": list(self.notes),
        }
