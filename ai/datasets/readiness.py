from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.datasets.pipeline import MLDatasetArtifact


@dataclass(frozen=True, slots=True)
class DatasetReadinessReport:
    ready: bool
    reasons: tuple[str, ...]
    row_count: int
    feature_count: int

    @property
    def status(self) -> str:
        return "DATASET READY" if self.ready else "DATASET NOT READY"


class DatasetReadinessChecker:
    def __init__(self, *, minimum_samples: int = 1000, maximum_class_share: float = 0.95):
        self.minimum_samples = minimum_samples
        self.maximum_class_share = maximum_class_share

    def check(self, artifact: MLDatasetArtifact) -> DatasetReadinessReport:
        reasons: list[str] = []
        samples = artifact.samples
        if len(samples) < self.minimum_samples:
            reasons.append("INSUFFICIENT_SAMPLES")
        timestamps = [sample.timestamp for sample in samples]
        if len(set(timestamps)) != len(timestamps) or any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            reasons.append("TIMESTAMP_PROBLEM")
        if any(sample.label.label_end_timestamp <= sample.timestamp for sample in samples):
            reasons.append("LEAKAGE_OR_INVALID_LABEL_WINDOW")
        if any(not all(self._finite(value) for value in sample.features.values()) for sample in samples):
            reasons.append("INVALID_FEATURE")
        if samples and any(
            sample.features.get(f"{timeframe.lower()}_available") != 1.0
            for sample in samples for timeframe in artifact.metadata.timeframes
        ):
            reasons.append("MISSING_DATA")
        if any(report.missing_rows or report.incomplete_rows for report in artifact.quality_reports.values() if report.total_rows):
            reasons.append("MISSING_DATA")
        if any(report.timestamp_order_errors or report.timezone_errors for report in artifact.quality_reports.values() if report.total_rows):
            reasons.append("TIMESTAMP_PROBLEM")
        if any(report.invalid_rows for report in artifact.quality_reports.values() if report.total_rows):
            reasons.append("INVALID_FEATURE")
        distribution = artifact.statistics.get("class_distribution", {})
        if distribution and (max(distribution.values()) > self.maximum_class_share or any(value == 0 for value in distribution.values())):
            reasons.append("LABEL_IMBALANCE")
        expected_order = {"TRAIN": 0, "VALIDATION": 1, "TEST": 2}
        split_order = [expected_order.get(sample.split, -1) for sample in samples]
        if split_order != sorted(split_order) or -1 in split_order:
            reasons.append("TIMESTAMP_PROBLEM")
        return DatasetReadinessReport(not reasons, tuple(dict.fromkeys(reasons)), len(samples), artifact.metadata.feature_count)

    def check_files(self, metadata_path: str | Path) -> DatasetReadinessReport:
        import json
        import pandas as pd

        metadata_path = Path(metadata_path)
        if not metadata_path.exists():
            return DatasetReadinessReport(False, ("MISSING_DATA",), 0, 0)
        metadata: dict[str, Any] = json.loads(metadata_path.read_text(encoding="utf-8"))
        stem = metadata_path.name.removesuffix("_dataset_metadata.json")
        features_path = metadata_path.with_name(f"{stem}_features.parquet")
        labels_path = metadata_path.with_name(f"{stem}_labels.parquet")
        if not features_path.exists() or not labels_path.exists():
            return DatasetReadinessReport(False, ("MISSING_DATA",), 0, int(metadata.get("feature_count", 0)))
        features, labels = pd.read_parquet(features_path), pd.read_parquet(labels_path)
        reasons: list[str] = []
        if len(features) != len(labels) or len(features) != int(metadata.get("row_count", -1)):
            reasons.append("MISSING_DATA")
        if len(features) < self.minimum_samples:
            reasons.append("INSUFFICIENT_SAMPLES")
        if "timestamp" not in features or features["timestamp"].duplicated().any() or not features["timestamp"].is_monotonic_increasing:
            reasons.append("TIMESTAMP_PROBLEM")
        numeric = features.drop(columns=[name for name in ("timestamp", "symbol", "split") if name in features])
        if numeric.isnull().any().any() or not numeric.map(self._finite).all().all():
            reasons.append("INVALID_FEATURE")
        if {"timestamp", "label_end_timestamp"} <= set(labels) and not (labels["label_end_timestamp"] > labels["timestamp"]).all():
            reasons.append("LEAKAGE_OR_INVALID_LABEL_WINDOW")
        distribution = labels["classification"].value_counts(normalize=True) if "classification" in labels else None
        if (
            distribution is None or distribution.empty or distribution.max() > self.maximum_class_share
            or set(distribution.index) != {"UP", "DOWN", "NEUTRAL"}
        ):
            reasons.append("LABEL_IMBALANCE")
        return DatasetReadinessReport(
            not reasons, tuple(dict.fromkeys(reasons)), len(features), int(metadata.get("feature_count", len(numeric.columns))),
        )

    @staticmethod
    def _finite(value: Any) -> bool:
        try:
            from math import isfinite
            return isfinite(float(value))
        except (TypeError, ValueError):
            return False
