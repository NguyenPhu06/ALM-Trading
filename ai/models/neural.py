from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ai.training.config import TrainingConfig
from ai.training.reproducibility import set_reproducible_seed


@dataclass(frozen=True, slots=True)
class EpochMetrics:
    epoch: int
    train_loss: float
    validation_loss: float
    train_accuracy: float
    validation_accuracy: float


@dataclass(frozen=True, slots=True)
class TrainingHistory:
    epochs: tuple[EpochMetrics, ...]
    stopped_early: bool
    best_epoch: int
    overfitting_status: str


class NumpyMLPClassifier:
    """Small deterministic MLP for research; it has no execution or order interface."""

    ARCHITECTURE_VERSION = "numpy_mlp.v1"

    def __init__(self, input_units: int, config: TrainingConfig):
        self.input_units = input_units
        self.config = config
        self.model_version = self.ARCHITECTURE_VERSION
        self.weights: list[np.ndarray] = []
        self.biases: list[np.ndarray] = []
        self.history: TrainingHistory | None = None
        self._initialize()

    def _initialize(self) -> None:
        set_reproducible_seed(self.config.random_seed)
        rng = np.random.default_rng(self.config.random_seed)
        dimensions = [self.input_units] + [self.config.hidden_units] * self.config.hidden_layers + [3]
        self.weights = []
        self.biases = []
        for index, (source, target) in enumerate(zip(dimensions, dimensions[1:])):
            scale = np.sqrt(2.0 / source) if index < len(dimensions) - 2 else np.sqrt(1.0 / source)
            self.weights.append(rng.normal(0.0, scale, size=(source, target)))
            self.biases.append(np.zeros(target, dtype=float))

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        shifted = logits - np.max(logits, axis=1, keepdims=True)
        values = np.exp(shifted)
        return values / np.sum(values, axis=1, keepdims=True)

    def _forward(self, matrix: np.ndarray, *, training: bool, rng=None):
        activations = [matrix]
        preactivations: list[np.ndarray] = []
        masks: list[np.ndarray | None] = []
        current = matrix
        for weights, bias in zip(self.weights[:-1], self.biases[:-1]):
            preactivation = current @ weights + bias
            current = np.maximum(preactivation, 0.0)
            mask = None
            if training and self.config.dropout > 0:
                keep = 1.0 - self.config.dropout
                mask = (rng.random(current.shape) < keep).astype(float) / keep
                current = current * mask
            preactivations.append(preactivation)
            masks.append(mask)
            activations.append(current)
        probabilities = self._softmax(current @ self.weights[-1] + self.biases[-1])
        return probabilities, activations, preactivations, masks

    def fit(
        self, train_matrix: np.ndarray, train_labels: np.ndarray,
        validation_matrix: np.ndarray, validation_labels: np.ndarray,
        *, class_weights: np.ndarray | None = None,
    ) -> TrainingHistory:
        if train_matrix.shape[1] != self.input_units or validation_matrix.shape[1] != self.input_units:
            raise ValueError("model input width does not match architecture")
        if not len(train_matrix) or not len(validation_matrix):
            raise ValueError("TRAIN and VALIDATION must both be non-empty")
        set_reproducible_seed(self.config.random_seed)
        rng = np.random.default_rng(self.config.random_seed)
        weights_by_sample = class_weights[train_labels] if class_weights is not None else np.ones(len(train_labels))
        best_loss = float("inf")
        best_epoch = 0
        best_state = self.state_dict()
        wait = 0
        records: list[EpochMetrics] = []
        stopped = False
        targets = np.eye(3)[train_labels]
        for epoch in range(1, self.config.epochs + 1):
            for start in range(0, len(train_matrix), self.config.batch_size):
                end = min(len(train_matrix), start + self.config.batch_size)
                batch = train_matrix[start:end]
                labels = train_labels[start:end]
                target = targets[start:end]
                sample_weights = weights_by_sample[start:end]
                probabilities, activations, preactivations, masks = self._forward(batch, training=True, rng=rng)
                delta = (probabilities - target) * sample_weights[:, None] / max(1.0, float(np.sum(sample_weights)))
                weight_gradients = [np.zeros_like(value) for value in self.weights]
                bias_gradients = [np.zeros_like(value) for value in self.biases]
                weight_gradients[-1] = activations[-1].T @ delta
                bias_gradients[-1] = np.sum(delta, axis=0)
                propagated = delta @ self.weights[-1].T
                for layer in range(len(self.weights) - 2, -1, -1):
                    if masks[layer] is not None:
                        propagated *= masks[layer]
                    propagated *= preactivations[layer] > 0.0
                    weight_gradients[layer] = activations[layer].T @ propagated
                    bias_gradients[layer] = np.sum(propagated, axis=0)
                    if layer > 0:
                        propagated = propagated @ self.weights[layer].T
                for layer in range(len(self.weights)):
                    self.weights[layer] -= self.config.learning_rate * weight_gradients[layer]
                    self.biases[layer] -= self.config.learning_rate * bias_gradients[layer]
            train_probabilities = self.predict_proba(train_matrix)
            validation_probabilities = self.predict_proba(validation_matrix)
            train_loss = self._loss(train_probabilities, train_labels)
            validation_loss = self._loss(validation_probabilities, validation_labels)
            records.append(EpochMetrics(
                epoch, train_loss, validation_loss,
                self._accuracy(train_probabilities, train_labels),
                self._accuracy(validation_probabilities, validation_labels),
            ))
            if validation_loss < best_loss - self.config.minimum_improvement:
                best_loss, best_epoch, wait = validation_loss, epoch, 0
                best_state = self.state_dict()
            else:
                wait += 1
                if self.config.early_stopping and wait >= self.config.early_stopping_patience:
                    stopped = True
                    break
        self.load_state_dict(best_state)
        best_record = records[best_epoch - 1] if best_epoch else records[-1]
        overfitting = (
            best_record.validation_loss - best_record.train_loss > self.config.overfitting_loss_gap
            or best_record.train_accuracy - best_record.validation_accuracy > 0.15
        )
        self.history = TrainingHistory(
            tuple(records), stopped, best_epoch or records[-1].epoch,
            "POSSIBLE_OVERFITTING" if overfitting else "NO_CLEAR_OVERFITTING",
        )
        return self.history

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        if matrix.ndim != 2 or matrix.shape[1] != self.input_units:
            raise ValueError("prediction matrix has invalid shape")
        probabilities, *_ = self._forward(matrix, training=False)
        return probabilities

    @staticmethod
    def _loss(probabilities: np.ndarray, labels: np.ndarray) -> float:
        selected = np.clip(probabilities[np.arange(len(labels)), labels], 1e-12, 1.0)
        return -float(np.mean(np.log(selected)))

    @staticmethod
    def _accuracy(probabilities: np.ndarray, labels: np.ndarray) -> float:
        return float(np.mean(np.argmax(probabilities, axis=1) == labels))

    def state_dict(self) -> dict[str, object]:
        return {
            "input_units": self.input_units,
            "weights": [value.copy() for value in self.weights],
            "biases": [value.copy() for value in self.biases],
            "model_version": self.model_version,
        }

    def load_state_dict(self, state: dict[str, object]) -> None:
        if int(state["input_units"]) != self.input_units:
            raise ValueError("serialized model input width is incompatible")
        weights = [np.asarray(value, dtype=float).copy() for value in state["weights"]]
        biases = [np.asarray(value, dtype=float).copy() for value in state["biases"]]
        if len(weights) != len(self.weights) or any(a.shape != b.shape for a, b in zip(weights, self.weights)):
            raise ValueError("serialized model architecture is incompatible")
        self.weights, self.biases = weights, biases
        self.model_version = str(state.get("model_version", self.ARCHITECTURE_VERSION))
