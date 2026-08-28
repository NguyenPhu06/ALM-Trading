"""Model memory: what every model was, and how it has held up (sections 13, 20).

A registry knows which model is authoritative now. Memory knows what came
before — the data each model was trained on, the ranges it was validated over,
what it scored, and how its feature groups' contributions have moved from one
version to the next.

Section 20's rule is repeated here because it is easy to forget when a table of
importances looks so decisive: these are **associations measured on held-out
data**. Nothing in this module establishes that a feature causes anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from ai.dataset.features import FEATURE_GROUPS

CAUSALITY_DISCLAIMER = (
    "Feature importance is permutation-based association measured on held-out data. "
    "It does not establish causality, and correlated features may share importance "
    "arbitrarily between them."
)

# Section 20's list, expressed in this codebase's group names.
TRACKED_GROUPS: tuple[str, ...] = tuple(FEATURE_GROUPS.keys())


@dataclass(frozen=True, slots=True)
class ModelPerformanceEntry:
    """Section 13. One model's complete record, kept after it is superseded."""

    model_id: str
    version: str
    features: tuple[str, ...] = ()
    training_range: tuple[datetime | None, datetime | None] = (None, None)
    validation_range: tuple[datetime | None, datetime | None] = (None, None)
    test_range: tuple[datetime | None, datetime | None] = (None, None)
    sample_count: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    regime_metrics: dict[str, Any] = field(default_factory=dict)
    session_metrics: dict[str, Any] = field(default_factory=dict)
    drawdown: float | None = None
    calibration: dict[str, Any] = field(default_factory=dict)
    status: str = "EXPERIMENTAL"
    task_key: str | None = None
    feature_version: str | None = None
    dataset_version: str | None = None
    trained_at: datetime | None = None
    importance: dict[str, float] = field(default_factory=dict)
    edge_verdict: str = "NO_EDGE"

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id, "version": self.version,
            "features": list(self.features),
            "training_range": [_stamp(self.training_range[0]), _stamp(self.training_range[1])],
            "validation_range": [_stamp(self.validation_range[0]),
                                 _stamp(self.validation_range[1])],
            "test_range": [_stamp(self.test_range[0]), _stamp(self.test_range[1])],
            "sample_count": self.sample_count, "metrics": dict(self.metrics),
            "regime_metrics": dict(self.regime_metrics),
            "session_metrics": dict(self.session_metrics), "drawdown": self.drawdown,
            "calibration": dict(self.calibration), "status": self.status,
            "task_key": self.task_key, "feature_version": self.feature_version,
            "dataset_version": self.dataset_version, "trained_at": _stamp(self.trained_at),
            "importance": dict(self.importance), "edge_verdict": self.edge_verdict,
        }


class ModelMemory:
    """Append-only history of model records, keyed by model id."""

    def __init__(self, repository: Any = None):
        self.repository = repository
        self._entries: dict[str, ModelPerformanceEntry] = {}
        self._order: list[str] = []

    # ------------------------------------------------------------------ write
    def remember(self, record: Any, *, drawdown: float | None = None,
                 sample_count: int | None = None,
                 ranges: Mapping[str, Any] | None = None) -> ModelPerformanceEntry:
        """Record a model. Re-remembering the same id updates it in place."""
        ranges = ranges or {}
        test_metrics = dict(getattr(record, "test_metrics", {}) or {})
        entry = ModelPerformanceEntry(
            model_id=str(record.model_id), version=str(record.model_version),
            features=tuple(getattr(record, "feature_names", ()) or ()),
            training_range=_range(ranges.get("training")),
            validation_range=_range(ranges.get("validation")),
            test_range=_range(ranges.get("test")),
            sample_count=int(sample_count if sample_count is not None
                             else test_metrics.get("samples", 0) or 0),
            metrics=test_metrics,
            regime_metrics=dict(getattr(record, "regime_metrics", {}) or {}),
            session_metrics=dict(getattr(record, "session_metrics", {}) or {}),
            drawdown=drawdown,
            calibration=dict(getattr(record, "calibration", {}) or {}),
            status=str(getattr(record, "state", "EXPERIMENTAL")),
            task_key=getattr(getattr(record, "task", None), "key", None),
            feature_version=getattr(record, "feature_version", None),
            dataset_version=getattr(record, "training_dataset_version", None),
            trained_at=getattr(record, "training_timestamp", None),
            importance=group_importance(getattr(record, "explainability", {}) or {}),
            edge_verdict=str(getattr(record, "edge_verdict", "NO_EDGE")))

        if entry.model_id not in self._entries:
            self._order.append(entry.model_id)
        self._entries[entry.model_id] = entry
        return entry

    def load(self, records: Sequence[Any]) -> int:
        for record in records:
            self.remember(record)
        return len(self._entries)

    # ------------------------------------------------------------------- read
    def get(self, model_id: str) -> ModelPerformanceEntry | None:
        return self._entries.get(str(model_id))

    def history(self, task_key: str | None = None) -> list[ModelPerformanceEntry]:
        entries = [self._entries[model_id] for model_id in self._order]
        if task_key is not None:
            entries = [entry for entry in entries if entry.task_key == task_key]
        return sorted(entries, key=_trained_at_key)

    def latest(self, task_key: str | None = None) -> ModelPerformanceEntry | None:
        entries = self.history(task_key)
        return entries[-1] if entries else None

    # ------------------------------------------------- section 20: importance
    def importance_history(self, task_key: str | None = None) -> dict[str, Any]:
        """How each feature group's measured contribution moved across versions."""
        entries = self.history(task_key)
        versions = [entry.version for entry in entries]
        groups: dict[str, list[float | None]] = {}
        for group in TRACKED_GROUPS:
            groups[group] = [entry.importance.get(group) for entry in entries]
        return {"versions": versions, "models": [entry.model_id for entry in entries],
                "groups": groups, "disclaimer": CAUSALITY_DISCLAIMER}

    def compare_importance(self, left: str, right: str) -> dict[str, Any]:
        """Difference in measured contribution between two models, per group."""
        first = self.get(left)
        second = self.get(right)
        if first is None or second is None:
            raise KeyError(f"unknown model: {left if first is None else right}")
        deltas: dict[str, float | None] = {}
        for group in sorted(set(first.importance) | set(second.importance)):
            before = first.importance.get(group)
            after = second.importance.get(group)
            deltas[group] = (after - before) if (before is not None and after is not None) \
                else None
        moved = {group: value for group, value in deltas.items() if value is not None}
        return {"from": left, "to": right, "deltas": deltas,
                "largest_increase": max(moved, key=moved.get) if moved else None,
                "largest_decrease": min(moved, key=moved.get) if moved else None,
                "disclaimer": CAUSALITY_DISCLAIMER}

    def summary(self) -> dict[str, Any]:
        entries = self.history()
        by_status: dict[str, int] = {}
        for entry in entries:
            by_status[entry.status] = by_status.get(entry.status, 0) + 1
        return {"models": len(entries), "by_status": by_status,
                "latest": entries[-1].as_dict() if entries else None,
                "disclaimer": CAUSALITY_DISCLAIMER}


def group_importance(explainability: Mapping[str, Any]) -> dict[str, float]:
    """Pull the per-group importances out of a training report's explainability."""
    groups = explainability.get("groups") if isinstance(explainability, Mapping) else None
    if not isinstance(groups, Sequence):
        return {}
    result: dict[str, float] = {}
    for item in groups:
        if not isinstance(item, Mapping):
            continue
        name = item.get("group")
        value = item.get("importance")
        if name is None or value is None:
            continue
        try:
            result[str(name)] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def _range(value: Any) -> tuple[datetime | None, datetime | None]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) and len(value) == 2:
        return (value[0], value[1])
    return (None, None)


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def _trained_at_key(entry: ModelPerformanceEntry) -> datetime:
    """Naive and aware timestamps must not be compared; normalise to UTC first."""
    stamp = entry.trained_at
    if stamp is None:
        return _EPOCH
    return stamp if stamp.tzinfo is not None else stamp.replace(tzinfo=timezone.utc)
