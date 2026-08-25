from __future__ import annotations

from pathlib import Path

import numpy as np

from ai.models.neural import NumpyMLPClassifier
from ai.training.config import TrainingConfig


def save_model(model: NumpyMLPClassifier, path: str | Path) -> Path:
    path = Path(path)
    if path.exists():
        raise FileExistsError("model file is immutable and already exists")
    payload = {
        "input_units": np.asarray([model.input_units], dtype=int),
        "model_version": np.asarray([model.model_version]),
        "layer_count": np.asarray([len(model.weights)], dtype=int),
    }
    for index, value in enumerate(model.weights):
        payload[f"weight_{index}"] = value
    for index, value in enumerate(model.biases):
        payload[f"bias_{index}"] = value
    np.savez_compressed(path, **payload)
    return path


def load_model(path: str | Path, config: TrainingConfig) -> NumpyMLPClassifier:
    with np.load(Path(path), allow_pickle=False) as payload:
        input_units = int(payload["input_units"][0])
        layer_count = int(payload["layer_count"][0])
        model = NumpyMLPClassifier(input_units, config)
        model.load_state_dict({
            "input_units": input_units,
            "model_version": str(payload["model_version"][0]),
            "weights": [payload[f"weight_{index}"] for index in range(layer_count)],
            "biases": [payload[f"bias_{index}"] for index in range(layer_count)],
        })
    return model
