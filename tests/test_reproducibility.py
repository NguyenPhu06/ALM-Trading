import numpy as np

from ai.models import NumpyMLPClassifier
from tests.phase5_helpers import classification_data, training_config


def test_same_seed_config_and_data_produce_identical_model():
    _, matrix, labels, _ = classification_data(60)
    config = training_config(seed=99)
    first = NumpyMLPClassifier(matrix.shape[1], config)
    second = NumpyMLPClassifier(matrix.shape[1], config)
    first.fit(matrix[:40], labels[:40], matrix[40:50], labels[40:50])
    second.fit(matrix[:40], labels[:40], matrix[40:50], labels[40:50])
    assert np.array_equal(first.predict_proba(matrix[50:]), second.predict_proba(matrix[50:]))
    assert first.history == second.history
