from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

from ai.training.imbalance import CLASS_NAMES


@dataclass(frozen=True, slots=True)
class PerClassMetrics:
    precision: float
    recall: float
    f1: float
    support: int


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    accuracy: float
    balanced_accuracy: float
    per_class: dict[str, PerClassMetrics]
    confusion_matrix: tuple[tuple[int, ...], ...]
    roc_auc: dict[str, float | None]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def classification_metrics(labels: np.ndarray, probabilities: np.ndarray) -> ClassificationMetrics:
    labels = np.asarray(labels, dtype=int)
    probabilities = np.asarray(probabilities, dtype=float)
    if probabilities.shape != (len(labels), 3):
        raise ValueError("classification probabilities must have shape (rows, 3)")
    predictions = np.argmax(probabilities, axis=1)
    matrix = np.zeros((3, 3), dtype=int)
    for actual, predicted in zip(labels, predictions):
        matrix[actual, predicted] += 1
    per_class = {}
    auc = {}
    for index, name in enumerate(CLASS_NAMES):
        true_positive = int(matrix[index, index])
        false_positive = int(matrix[:, index].sum() - true_positive)
        false_negative = int(matrix[index, :].sum() - true_positive)
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[name] = PerClassMetrics(precision, recall, f1, int(matrix[index, :].sum()))
        auc[name] = _binary_auc(labels == index, probabilities[:, index])
    recalls = [value.recall for value in per_class.values()]
    return ClassificationMetrics(
        float(np.mean(predictions == labels)), float(np.mean(recalls)), per_class,
        tuple(tuple(int(value) for value in row) for row in matrix), auc,
    )


def _binary_auc(positive: np.ndarray, scores: np.ndarray) -> float | None:
    positive_scores = scores[positive]
    negative_scores = scores[~positive]
    if not len(positive_scores) or not len(negative_scores):
        return None
    comparisons = positive_scores[:, None] - negative_scores[None, :]
    return float((np.sum(comparisons > 0) + 0.5 * np.sum(comparisons == 0)) / comparisons.size)
