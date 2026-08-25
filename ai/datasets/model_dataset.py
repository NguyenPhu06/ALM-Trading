from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ai.models import ModelInput
from ai.training.imbalance import CLASS_TO_INDEX


@dataclass(frozen=True, slots=True)
class ModelDatasetPartition:
    name: str
    inputs: tuple[ModelInput, ...]
    matrix: np.ndarray
    labels: np.ndarray
    outcomes: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class PreparedModelDataset:
    dataset_version: str
    feature_version: str
    feature_names: tuple[str, ...]
    train: ModelDatasetPartition
    validation: ModelDatasetPartition
    test: ModelDatasetPartition
    metadata: dict[str, Any]


class ModelDatasetLoader:
    """Loads immutable Phase 4 artifacts without refitting preprocessing."""

    def load(self, metadata_path: str | Path) -> PreparedModelDataset:
        import pandas as pd

        metadata_path = Path(metadata_path)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        stem = metadata_path.name.removesuffix("_dataset_metadata.json")
        features = pd.read_parquet(metadata_path.with_name(f"{stem}_features.parquet"))
        labels = pd.read_parquet(metadata_path.with_name(f"{stem}_labels.parquet"))
        if len(features) != len(labels) or len(features) != int(metadata["row_count"]):
            raise ValueError("feature and label artifact rows are misaligned")
        feature_names = tuple(metadata["scaler"]["feature_names"])
        missing = [name for name in feature_names if name not in features.columns]
        if missing:
            raise ValueError(f"model dataset is missing features: {', '.join(missing)}")
        feature_times = pd.to_datetime(features["timestamp"], utc=True)
        label_times = pd.to_datetime(labels["timestamp"], utc=True)
        if not feature_times.equals(label_times):
            raise ValueError("features and labels are not anchored to identical timestamps")
        if feature_times.duplicated().any() or not feature_times.is_monotonic_increasing:
            raise ValueError("model dataset timestamps must be strictly chronological")
        split_values = tuple(str(value) for value in features["split"])
        order = {"TRAIN": 0, "VALIDATION": 1, "TEST": 2}
        numeric_order = [order.get(value, -1) for value in split_values]
        if -1 in numeric_order or numeric_order != sorted(numeric_order):
            raise ValueError("model dataset splits are shuffled or invalid")
        classifications = tuple(str(value) for value in labels["classification"])
        if any(value not in CLASS_TO_INDEX for value in classifications):
            raise ValueError("unsupported classification label")
        records = []
        for index in range(len(features)):
            timestamp = feature_times.iloc[index].to_pydatetime()
            values = tuple(float(features.iloc[index][name]) for name in feature_names)
            records.append(ModelInput(
                timestamp, str(features.iloc[index]["symbol"]), values, feature_names,
                str(metadata["feature_version"]), str(metadata["dataset_id"]),
            ))
        partitions = {
            name: self._partition(
                name, [index for index, split in enumerate(split_values) if split == name],
                records, features, labels, feature_names, classifications,
            )
            for name in order
        }
        if any(len(partition.inputs) == 0 for partition in partitions.values()):
            raise ValueError("TRAIN, VALIDATION, and TEST must all be non-empty")
        return PreparedModelDataset(
            str(metadata["dataset_id"]), str(metadata["feature_version"]), feature_names,
            partitions["TRAIN"], partitions["VALIDATION"], partitions["TEST"], metadata,
        )

    @staticmethod
    def _partition(name, indices, records, features, labels, feature_names, classifications) -> ModelDatasetPartition:
        matrix = np.asarray([[float(features.iloc[index][feature]) for feature in feature_names] for index in indices], dtype=float)
        targets = np.asarray([CLASS_TO_INDEX[classifications[index]] for index in indices], dtype=int)
        outcome_fields = (
            "future_return_1", "future_return_3", "future_return_5", "future_return_10",
            "maximum_favorable_excursion", "maximum_adverse_excursion", "classification",
        )
        outcomes = tuple({field: labels.iloc[index][field] for field in outcome_fields} for index in indices)
        return ModelDatasetPartition(name, tuple(records[index] for index in indices), matrix, targets, outcomes)
