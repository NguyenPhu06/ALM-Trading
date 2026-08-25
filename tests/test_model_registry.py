import tempfile
from pathlib import Path

import numpy as np
import pytest

from ai.models import NumpyMLPClassifier
from ai.models.registry import ImmutableModelRegistry, ModelRegistryMetadata
from ai.training.experiments import JsonExperimentTracker
from tests.phase5_helpers import classification_data, training_config


def test_registry_is_immutable_loadable_and_writes_model_card():
    _, matrix, labels, _ = classification_data(45)
    config = training_config()
    model = NumpyMLPClassifier(matrix.shape[1], config)
    model.fit(matrix[:30], labels[:30], matrix[30:40], labels[30:40])
    names = tuple(f"feature_{index}" for index in range(matrix.shape[1]))
    scaler = {"feature_names": list(names), "means": {name: 0.0 for name in names},
              "standard_deviations": {name: 1.0 for name in names}, "fitted_split": "TRAIN"}
    metadata = ModelRegistryMetadata(
        model.model_version, "dataset.v1", "phase4.features.v1",
        ("2026-01-01", "2026-02-01"), ("2026-02-02", "2026-02-10"),
        ("2026-02-11", "2026-02-20"), config.as_dict(), {"accuracy": 0.5},
        "2026-08-24T00:00:00+00:00", names, scaler,
    )
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        registry = ImmutableModelRegistry(Path(directory) / "models")
        path = registry.register(model, metadata)
        loaded, loaded_metadata = registry.load(model.model_version)
        assert np.array_equal(model.predict_proba(matrix[40:]), loaded.predict_proba(matrix[40:]))
        assert loaded_metadata == metadata
        assert (path / "MODEL_CARD.md").exists()
        with pytest.raises(FileExistsError):
            registry.register(model, metadata)
        experiment = JsonExperimentTracker(Path(directory) / "experiments").record(
            model_version=model.model_version, dataset_version="dataset.v1",
            feature_version="phase4.features.v1", features=names,
            hyperparameters=config.as_dict(), metrics={"accuracy": 0.5},
        )
        assert experiment.experiment_id.startswith("exp_")
