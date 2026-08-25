from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai.models.neural import NumpyMLPClassifier
from ai.models.registry.serialization import load_model, save_model
from ai.training.config import TrainingConfig


@dataclass(frozen=True, slots=True)
class ModelRegistryMetadata:
    model_version: str
    dataset_version: str
    feature_version: str
    training_period: tuple[str, str]
    validation_period: tuple[str, str]
    test_period: tuple[str, str]
    hyperparameters: dict[str, Any]
    metrics: dict[str, Any]
    training_timestamp: str
    features: tuple[str, ...]
    scaler: dict[str, Any]
    purpose: str = "THREE_CLASS_MARKET_DIRECTION_RESEARCH"
    limitations: tuple[str, ...] = (
        "NOT_A_TRADING_SIGNAL", "NOT_CALIBRATED_UNLESS_REPORTED", "NO_LIVE_EXECUTION",
    )
    known_failure_modes: tuple[str, ...] = (
        "REGIME_SHIFT", "CLASS_IMBALANCE", "MISSING_OR_STALE_MARKET_DATA",
    )


class ImmutableModelRegistry:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def register(self, model: NumpyMLPClassifier, metadata: ModelRegistryMetadata) -> Path:
        if model.model_version != metadata.model_version:
            raise ValueError("model and registry metadata versions differ")
        directory = self.root / metadata.model_version
        if directory.exists():
            raise FileExistsError("model version already exists; registry entries are immutable")
        directory.mkdir(parents=True)
        save_model(model, directory / "model.npz")
        payload = self._jsonable(asdict(metadata))
        (directory / "metadata.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        (directory / "MODEL_CARD.md").write_text(self._model_card(metadata), encoding="utf-8")
        return directory

    def load(self, model_version: str) -> tuple[NumpyMLPClassifier, ModelRegistryMetadata]:
        directory = self.root / model_version
        payload = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        metadata = ModelRegistryMetadata(
            **{**payload,
               "training_period": tuple(payload["training_period"]),
               "validation_period": tuple(payload["validation_period"]),
               "test_period": tuple(payload["test_period"]),
               "features": tuple(payload["features"]),
               "limitations": tuple(payload["limitations"]),
               "known_failure_modes": tuple(payload["known_failure_modes"])},
        )
        config = TrainingConfig(**metadata.hyperparameters)
        return load_model(directory / "model.npz", config), metadata

    @staticmethod
    def metadata_from_training(report, dataset) -> ModelRegistryMetadata:
        neural_metrics = report.evaluations["neural_network"]
        return ModelRegistryMetadata(
            report.model_version, report.dataset_version, report.feature_version,
            (dataset.train.inputs[0].timestamp.isoformat(), dataset.train.inputs[-1].timestamp.isoformat()),
            (dataset.validation.inputs[0].timestamp.isoformat(), dataset.validation.inputs[-1].timestamp.isoformat()),
            (dataset.test.inputs[0].timestamp.isoformat(), dataset.test.inputs[-1].timestamp.isoformat()),
            report.model.config.as_dict(), {
                "test_evaluation": ImmutableModelRegistry._jsonable(neural_metrics),
                "training_history": ImmutableModelRegistry._jsonable(report.history),
                "overfitting_status": report.history.overfitting_status,
            },
            datetime.now(timezone.utc).isoformat(), dataset.feature_names,
            dict(dataset.metadata["scaler"]),
        )

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        if is_dataclass(value):
            return cls._jsonable(asdict(value))
        if isinstance(value, dict):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._jsonable(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    @staticmethod
    def _model_card(metadata: ModelRegistryMetadata) -> str:
        return f"""# Model card: {metadata.model_version}

## Mục đích

{metadata.purpose}. Model chỉ phục vụ nghiên cứu xác suất UP/DOWN/NEUTRAL và không tạo lệnh.

## Dataset và feature

- Dataset: `{metadata.dataset_version}`
- Feature version: `{metadata.feature_version}`
- Số feature: {len(metadata.features)}
- TRAIN: {metadata.training_period[0]} → {metadata.training_period[1]}
- VALIDATION: {metadata.validation_period[0]} → {metadata.validation_period[1]}
- TEST: {metadata.test_period[0]} → {metadata.test_period[1]}

## Giới hạn

{chr(10).join(f'- {value}' for value in metadata.limitations)}

## Failure mode đã biết

{chr(10).join(f'- {value}' for value in metadata.known_failure_modes)}

Metrics và hyperparameter đầy đủ nằm trong `metadata.json`. Confidence không được xem là xác suất thực nếu calibration report chưa chứng minh.
"""
