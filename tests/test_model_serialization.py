import tempfile
from pathlib import Path

import numpy as np
import pytest

from ai.models import NumpyMLPClassifier
from ai.models.registry import load_model, save_model
from tests.phase5_helpers import classification_data, training_config


def test_loaded_model_prediction_matches_before_save():
    _, matrix, labels, _ = classification_data(45)
    config = training_config()
    model = NumpyMLPClassifier(matrix.shape[1], config)
    model.fit(matrix[:30], labels[:30], matrix[30:40], labels[30:40])
    before = model.predict_proba(matrix[40:])
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        path = Path(directory) / "model.npz"
        save_model(model, path)
        loaded = load_model(path, config)
        assert np.array_equal(before, loaded.predict_proba(matrix[40:]))
        with pytest.raises(FileExistsError):
            save_model(model, path)
