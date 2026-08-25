from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

import numpy as np

from ai.datasets.walk_forward import ExpandingWalkForward, WalkForwardWindow
from ai.evaluation.metrics import ClassificationMetrics, classification_metrics
from ai.models import NumpyMLPClassifier
from ai.training.config import TrainingConfig
from ai.training.imbalance import CLASS_NAMES, analyze_class_imbalance


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    window: WalkForwardWindow
    metrics: ClassificationMetrics
    best_epoch: int
    overfitting_status: str


class WalkForwardValidator:
    def __init__(self, windowing: ExpandingWalkForward, config: TrainingConfig):
        self.windowing = windowing
        self.config = config

    def validate(
        self, timestamps: Sequence[datetime], matrix: np.ndarray, labels: np.ndarray,
        outcomes: Sequence[Mapping[str, object]] | None = None,
    ) -> tuple[WalkForwardResult, ...]:
        del outcomes
        if len(timestamps) != len(matrix) or len(matrix) != len(labels):
            raise ValueError("walk-forward arrays must align")
        index_by_time = {timestamp: index for index, timestamp in enumerate(timestamps)}
        results = []
        for window in self.windowing.windows(timestamps):
            train_end = index_by_time[window.train_end] + 1
            validation_start = index_by_time[window.validation_start]
            validation_end = index_by_time[window.validation_end] + 1
            test_start = index_by_time[window.test_start]
            test_end = index_by_time[window.test_end] + 1
            imbalance = analyze_class_imbalance(labels[:train_end])
            class_weights = None
            if self.config.class_weighting:
                class_weights = np.asarray([imbalance.class_weights[name] for name in CLASS_NAMES], dtype=float)
            model = NumpyMLPClassifier(matrix.shape[1], self.config)
            history = model.fit(
                matrix[:train_end], labels[:train_end],
                matrix[validation_start:validation_end], labels[validation_start:validation_end],
                class_weights=class_weights,
            )
            probabilities = model.predict_proba(matrix[test_start:test_end])
            results.append(WalkForwardResult(
                window, classification_metrics(labels[test_start:test_end], probabilities),
                history.best_epoch, history.overfitting_status,
            ))
        return tuple(results)
