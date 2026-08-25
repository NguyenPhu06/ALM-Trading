from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ai.training.config import TrainingConfig


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / np.sum(exponentials, axis=1, keepdims=True)


class MajorityClassBaseline:
    model_version = "baseline.majority.v1"

    def __init__(self) -> None:
        self.probabilities: np.ndarray | None = None

    def fit(self, matrix: np.ndarray, labels: np.ndarray) -> "MajorityClassBaseline":
        del matrix
        counts = np.bincount(labels, minlength=3).astype(float)
        self.probabilities = counts / counts.sum()
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        if self.probabilities is None:
            raise ValueError("majority baseline is not fitted")
        return np.tile(self.probabilities, (len(matrix), 1))


class SoftmaxLogisticBaseline:
    model_version = "baseline.logistic.v1"

    def __init__(self) -> None:
        self.weights: np.ndarray | None = None
        self.bias: np.ndarray | None = None

    def fit(
        self, matrix: np.ndarray, labels: np.ndarray, *, config: TrainingConfig,
        class_weights: np.ndarray | None = None,
    ) -> "SoftmaxLogisticBaseline":
        self.weights = np.zeros((matrix.shape[1], 3), dtype=float)
        self.bias = np.zeros(3, dtype=float)
        targets = np.eye(3)[labels]
        sample_weights = class_weights[labels] if class_weights is not None else np.ones(len(labels))
        for _ in range(config.epochs):
            probabilities = _softmax(matrix @ self.weights + self.bias)
            gradient = (probabilities - targets) * sample_weights[:, None] / max(1, len(labels))
            self.weights -= config.learning_rate * matrix.T @ gradient
            self.bias -= config.learning_rate * np.sum(gradient, axis=0)
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        if self.weights is None or self.bias is None:
            raise ValueError("logistic baseline is not fitted")
        return _softmax(matrix @ self.weights + self.bias)


@dataclass(slots=True)
class DecisionStumpBaseline:
    model_version: str = "baseline.tree_stump.v1"
    feature_index: int | None = None
    threshold: float = 0.0
    left_probabilities: np.ndarray | None = None
    right_probabilities: np.ndarray | None = None

    def fit(self, matrix: np.ndarray, labels: np.ndarray) -> "DecisionStumpBaseline":
        best_loss = float("inf")
        for feature_index in range(matrix.shape[1]):
            threshold = float(np.median(matrix[:, feature_index]))
            left = matrix[:, feature_index] <= threshold
            right = ~left
            if not left.any() or not right.any():
                continue
            left_probabilities = self._distribution(labels[left])
            right_probabilities = self._distribution(labels[right])
            probabilities = np.where(left[:, None], left_probabilities, right_probabilities)
            loss = -float(np.mean(np.log(np.clip(probabilities[np.arange(len(labels)), labels], 1e-12, 1.0))))
            if loss < best_loss:
                best_loss = loss
                self.feature_index = feature_index
                self.threshold = threshold
                self.left_probabilities = left_probabilities
                self.right_probabilities = right_probabilities
        if self.feature_index is None:
            self.feature_index = 0
            self.left_probabilities = self.right_probabilities = self._distribution(labels)
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        if self.feature_index is None or self.left_probabilities is None or self.right_probabilities is None:
            raise ValueError("tree baseline is not fitted")
        left = matrix[:, self.feature_index] <= self.threshold
        return np.where(left[:, None], self.left_probabilities, self.right_probabilities)

    @staticmethod
    def _distribution(labels: np.ndarray) -> np.ndarray:
        counts = np.bincount(labels, minlength=3).astype(float) + 1e-9
        return counts / counts.sum()
