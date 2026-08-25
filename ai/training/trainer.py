from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import numpy as np

from ai.datasets.model_dataset import PreparedModelDataset
from ai.evaluation import ModelEvaluation, evaluate_model
from ai.models import (
    DecisionStumpBaseline, MajorityClassBaseline, NumpyMLPClassifier, SoftmaxLogisticBaseline,
    TrainingHistory,
)
from ai.training.config import TrainingConfig
from ai.training.imbalance import CLASS_NAMES, ClassImbalanceReport, analyze_class_imbalance


@dataclass(frozen=True, slots=True)
class TrainingReport:
    model: NumpyMLPClassifier
    model_version: str
    dataset_version: str
    feature_version: str
    history: TrainingHistory
    imbalance: ClassImbalanceReport
    evaluations: dict[str, ModelEvaluation]
    neural_network_beats_baseline: bool


class ResearchTrainer:
    """Fits on TRAIN, early-stops on VALIDATION, and evaluates TEST exactly once."""

    def __init__(self, config: TrainingConfig, *, calibration_bins: int):
        self.config = config
        self.calibration_bins = calibration_bins

    def train(self, dataset: PreparedModelDataset) -> TrainingReport:
        imbalance = analyze_class_imbalance(dataset.train.labels)
        class_weights = None
        if self.config.class_weighting:
            class_weights = np.asarray([imbalance.class_weights[name] for name in CLASS_NAMES], dtype=float)
        baselines = {
            "majority": MajorityClassBaseline().fit(dataset.train.matrix, dataset.train.labels),
            "logistic": SoftmaxLogisticBaseline().fit(
                dataset.train.matrix, dataset.train.labels, config=self.config, class_weights=class_weights,
            ),
            "tree_stump": DecisionStumpBaseline().fit(dataset.train.matrix, dataset.train.labels),
        }
        model = NumpyMLPClassifier(dataset.train.matrix.shape[1], self.config)
        history = model.fit(
            dataset.train.matrix, dataset.train.labels,
            dataset.validation.matrix, dataset.validation.labels,
            class_weights=class_weights,
        )
        version_payload = {
            "architecture": model.ARCHITECTURE_VERSION, "dataset": dataset.dataset_version,
            "feature": dataset.feature_version, "config": self.config.as_dict(),
        }
        digest = hashlib.sha256(json.dumps(version_payload, sort_keys=True).encode()).hexdigest()[:12]
        model.model_version = f"{model.ARCHITECTURE_VERSION}.{digest}"
        evaluations = {
            name: evaluate_model(
                baseline.model_version, dataset.test.labels,
                baseline.predict_proba(dataset.test.matrix), dataset.test.outcomes,
                calibration_bins=self.calibration_bins,
            )
            for name, baseline in baselines.items()
        }
        evaluations["neural_network"] = evaluate_model(
            model.model_version, dataset.test.labels, model.predict_proba(dataset.test.matrix),
            dataset.test.outcomes, calibration_bins=self.calibration_bins,
        )
        best_baseline = max(value.classification.balanced_accuracy for value in evaluations.values() if value is not evaluations["neural_network"])
        beats = evaluations["neural_network"].classification.balanced_accuracy > best_baseline
        return TrainingReport(
            model, model.model_version, dataset.dataset_version, dataset.feature_version,
            history, imbalance, evaluations, beats,
        )
