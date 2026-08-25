from __future__ import annotations

from datetime import timedelta

import numpy as np

from ai.models import ModelInput
from ai.training.config import TrainingConfig
from tests.phase4_helpers import BASE


def training_config(seed: int = 17) -> TrainingConfig:
    return TrainingConfig(
        learning_rate=0.03, batch_size=8, epochs=30, hidden_layers=1, hidden_units=8,
        dropout=0.0, early_stopping=True, early_stopping_patience=5,
        minimum_improvement=0.00001, random_seed=seed, class_weighting=True,
        overfitting_loss_gap=0.5,
    )


def classification_data(rows: int = 90, features: int = 6):
    index = np.arange(rows, dtype=float)
    matrix = np.column_stack([
        np.sin(index / (column + 2)) + np.cos(index / (column + 3))
        for column in range(features)
    ])
    labels = np.asarray([value % 3 for value in range(rows)], dtype=int)
    timestamps = [BASE + timedelta(minutes=15 * value) for value in range(rows)]
    outcomes = tuple({
        "future_return_5": (label - 1) * 0.001,
        "maximum_favorable_excursion": 0.002 + label * 0.0001,
        "maximum_adverse_excursion": -0.001 - label * 0.0001,
    } for label in labels)
    return timestamps, matrix, labels, outcomes


def model_inputs(timestamps, matrix):
    names = tuple(f"feature_{index}" for index in range(matrix.shape[1]))
    return tuple(ModelInput(
        timestamp, "EURUSD", tuple(row), names, "phase4.features.v1", "fixture.v1",
    ) for timestamp, row in zip(timestamps, matrix))
