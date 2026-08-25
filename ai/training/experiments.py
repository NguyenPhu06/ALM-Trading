from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class ExperimentRecord:
    experiment_id: str
    model_version: str
    dataset_version: str
    feature_version: str
    features: tuple[str, ...]
    hyperparameters: dict[str, Any]
    metrics: dict[str, Any]
    timestamp: str


class JsonExperimentTracker:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def record(self, *, model_version, dataset_version, feature_version, features, hyperparameters, metrics) -> ExperimentRecord:
        timestamp = datetime.now(timezone.utc).isoformat()
        digest = hashlib.sha256(f"{model_version}|{dataset_version}|{timestamp}".encode()).hexdigest()[:16]
        record = ExperimentRecord(
            f"exp_{digest}", model_version, dataset_version, feature_version,
            tuple(features), dict(hyperparameters), dict(metrics), timestamp,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{record.experiment_id}.json"
        if path.exists():
            raise FileExistsError("experiment record already exists")
        path.write_text(json.dumps(record.__dict__ if hasattr(record, "__dict__") else {
            "experiment_id": record.experiment_id, "model_version": record.model_version,
            "dataset_version": record.dataset_version, "feature_version": record.feature_version,
            "features": list(record.features), "hyperparameters": record.hyperparameters,
            "metrics": record.metrics, "timestamp": record.timestamp,
        }, indent=2, sort_keys=True), encoding="utf-8")
        return record
