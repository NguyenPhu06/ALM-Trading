import numpy as np

from ai.models import ModelPrediction, NumpyMLPClassifier
from tests.phase5_helpers import BASE, classification_data, training_config


def test_neural_model_outputs_three_normalized_probabilities():
    _, matrix, labels, _ = classification_data(60)
    model = NumpyMLPClassifier(matrix.shape[1], training_config())
    model.fit(matrix[:40], labels[:40], matrix[40:50], labels[40:50])
    probabilities = model.predict_proba(matrix[50:])
    assert probabilities.shape == (10, 3)
    assert np.all(probabilities >= 0) and np.all(probabilities <= 1)
    assert np.allclose(probabilities.sum(axis=1), 1.0)
    row = probabilities[0]
    prediction = ModelPrediction(BASE, "EURUSD", *map(float, row), float(row.max()), model.model_version, "phase4.features.v1")
    assert prediction.predicted_class in {"UP", "DOWN", "NEUTRAL"}
    assert not hasattr(prediction, "action")
