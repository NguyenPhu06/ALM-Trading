"""Multi-task MLP: one shared trunk, several heads.

Deliberately a small, reliable baseline rather than a deep network. The
architecture is modular so an LSTM / temporal CNN / transformer trunk can replace
the dense trunk later without touching the heads or the training loop.

The model outputs probabilities and expectations. It never outputs BUY or SELL —
that interpretation belongs to the Strategy Engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import logging

import numpy as np

from ai.training.reproducibility import set_reproducible_seed

logger = logging.getLogger(__name__)

# A standardized column sits near mean 0 / std 1. Anything far outside that says
# the caller forgot to apply the train-fitted scaler.
SCALE_TOLERANCE = 10.0

DIRECTION_CLASSES = ("UP", "DOWN", "NEUTRAL")
REGRESSION_HEADS = ("expected_return", "expected_mfe", "expected_mae")


@dataclass(frozen=True, slots=True)
class MultiTaskOutput:
    """What the model produces for one sample. No trade instruction anywhere."""

    direction_probability: dict[str, float]
    expected_return: float
    expected_mfe: float
    expected_mae: float
    volatility_probability: float
    confidence: float

    @property
    def predicted_class(self) -> str:
        return max(self.direction_probability, key=self.direction_probability.get)

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction_probability": dict(self.direction_probability),
            "expected_return": self.expected_return, "expected_mfe": self.expected_mfe,
            "expected_mae": self.expected_mae,
            "volatility_probability": self.volatility_probability,
            "confidence": self.confidence, "predicted_class": self.predicted_class,
        }


@dataclass(frozen=True, slots=True)
class TrainingHistory:
    epochs: tuple[dict[str, float], ...]
    best_epoch: int
    stopped_early: bool
    overfitting_status: str
    # Unscaled input trains to a useless model without erroring, so the fact is
    # recorded here and surfaces in the model record rather than passing silently.
    input_scaled: bool = True
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"epochs": [dict(row) for row in self.epochs], "best_epoch": self.best_epoch,
                "stopped_early": self.stopped_early,
                "overfitting_status": self.overfitting_status,
                "input_scaled": self.input_scaled, "warnings": list(self.warnings)}


@dataclass(frozen=True, slots=True)
class MultiTaskConfig:
    hidden_units: int = 32
    learning_rate: float = 0.01
    epochs: int = 120
    batch_size: int = 32
    random_seed: int = 42
    early_stopping_patience: int = 12
    minimum_improvement: float = 1e-4
    regression_weight: float = 0.3
    volatility_weight: float = 0.2
    class_weighting: bool = True
    overfitting_loss_gap: float = 0.20

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(values, -50, 50)))


class MultiTaskMLP:
    """Shared trunk -> {direction softmax, three regressions, volatility sigmoid}."""

    ARCHITECTURE_VERSION = "multitask_mlp.v1"

    def __init__(self, input_units: int, config: MultiTaskConfig | None = None):
        self.input_units = int(input_units)
        self.config = config or MultiTaskConfig()
        self.model_version = self.ARCHITECTURE_VERSION
        self.history: TrainingHistory | None = None
        self._initialise()

    def _initialise(self) -> None:
        set_reproducible_seed(self.config.random_seed)
        rng = np.random.default_rng(self.config.random_seed)
        hidden = self.config.hidden_units
        scale = np.sqrt(2.0 / max(self.input_units, 1))
        self.w_trunk = rng.normal(0.0, scale, size=(self.input_units, hidden))
        self.b_trunk = np.zeros(hidden)
        head_scale = np.sqrt(1.0 / max(hidden, 1))
        self.w_direction = rng.normal(0.0, head_scale, size=(hidden, len(DIRECTION_CLASSES)))
        self.b_direction = np.zeros(len(DIRECTION_CLASSES))
        self.w_regression = rng.normal(0.0, head_scale, size=(hidden, len(REGRESSION_HEADS)))
        self.b_regression = np.zeros(len(REGRESSION_HEADS))
        self.w_volatility = rng.normal(0.0, head_scale, size=(hidden, 1))
        self.b_volatility = np.zeros(1)

    # ------------------------------------------------------------------ forward
    def _forward(self, matrix: np.ndarray) -> dict[str, np.ndarray]:
        pre = matrix @ self.w_trunk + self.b_trunk
        hidden = np.maximum(pre, 0.0)                       # ReLU trunk
        return {
            "pre": pre, "hidden": hidden,
            "direction": _softmax(hidden @ self.w_direction + self.b_direction),
            "regression": hidden @ self.w_regression + self.b_regression,
            "volatility": _sigmoid(hidden @ self.w_volatility + self.b_volatility),
        }

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        return self._forward(np.asarray(matrix, dtype=float))["direction"]

    def predict(self, matrix: np.ndarray) -> list[MultiTaskOutput]:
        forward = self._forward(np.asarray(matrix, dtype=float))
        outputs: list[MultiTaskOutput] = []
        for index in range(len(matrix)):
            probabilities = forward["direction"][index]
            regression = forward["regression"][index]
            outputs.append(MultiTaskOutput(
                direction_probability={name: float(probabilities[position])
                                       for position, name in enumerate(DIRECTION_CLASSES)},
                expected_return=float(regression[0]), expected_mfe=float(regression[1]),
                expected_mae=float(regression[2]),
                volatility_probability=float(forward["volatility"][index][0]),
                confidence=float(probabilities.max()),
            ))
        return outputs

    # ------------------------------------------------------------------- train
    def fit(self, train: dict[str, np.ndarray],
            validation: dict[str, np.ndarray] | None = None) -> TrainingHistory:
        """Train on TRAIN, early-stop on VALIDATION. Never called during inference."""
        matrix = np.asarray(train["features"], dtype=float)
        direction = np.asarray(train["direction"], dtype=int)
        regression = np.asarray(train["regression"], dtype=float)
        volatility = np.asarray(train["volatility"], dtype=float).reshape(-1, 1)

        scaled, warnings = self._check_scaling(matrix)
        weights = self._class_weights(direction)
        rng = np.random.default_rng(self.config.random_seed)
        best_loss = np.inf
        best_state = self._state()
        best_epoch = 0
        patience = 0
        rows: list[dict[str, float]] = []
        stopped_early = False

        for epoch in range(1, self.config.epochs + 1):
            # Chronological order is preserved inside each batch; only batch
            # boundaries are permuted, which does not leak across time.
            order = rng.permutation(len(matrix))
            for start in range(0, len(order), self.config.batch_size):
                index = order[start:start + self.config.batch_size]
                self._step(matrix[index], direction[index], regression[index],
                           volatility[index], weights)

            train_loss = self._loss(matrix, direction, regression, volatility, weights)
            validation_loss = train_loss
            if validation and len(validation.get("features", ())):
                validation_loss = self._loss(
                    np.asarray(validation["features"], dtype=float),
                    np.asarray(validation["direction"], dtype=int),
                    np.asarray(validation["regression"], dtype=float),
                    np.asarray(validation["volatility"], dtype=float).reshape(-1, 1),
                    weights)
            rows.append({"epoch": epoch, "train_loss": float(train_loss),
                         "validation_loss": float(validation_loss)})

            if validation_loss < best_loss - self.config.minimum_improvement:
                best_loss, best_epoch, patience = validation_loss, epoch, 0
                best_state = self._state()
            else:
                patience += 1
                if patience >= self.config.early_stopping_patience:
                    stopped_early = True
                    break

        self._restore(best_state)
        gap = rows[best_epoch - 1]["validation_loss"] - rows[best_epoch - 1]["train_loss"] if rows else 0.0
        status = "OVERFITTING" if gap > self.config.overfitting_loss_gap else "ACCEPTABLE"
        self.history = TrainingHistory(tuple(rows), best_epoch, stopped_early, status,
                                       scaled, tuple(warnings))
        return self.history

    @staticmethod
    def _check_scaling(matrix: np.ndarray) -> tuple[bool, list[str]]:
        if matrix.size == 0:
            return True, []
        means = np.abs(matrix.mean(axis=0))
        deviations = matrix.std(axis=0)
        offenders = int(((means > SCALE_TOLERANCE) | (deviations > SCALE_TOLERANCE)).sum())
        if not offenders:
            return True, []
        message = (f"{offenders} feature column(s) look unscaled; fit the train-only "
                   "scaler before training or the model will not learn")
        logger.warning(message)
        return False, [message]

    def _class_weights(self, direction: np.ndarray) -> np.ndarray:
        if not self.config.class_weighting or len(direction) == 0:
            return np.ones(len(DIRECTION_CLASSES))
        counts = np.bincount(direction, minlength=len(DIRECTION_CLASSES)).astype(float)
        counts[counts == 0] = 1.0
        weights = counts.sum() / (len(DIRECTION_CLASSES) * counts)
        return weights

    def _step(self, matrix, direction, regression, volatility, weights) -> None:
        rows = max(len(matrix), 1)
        forward = self._forward(matrix)
        hidden = forward["hidden"]

        one_hot = np.zeros_like(forward["direction"])
        one_hot[np.arange(len(direction)), direction] = 1.0
        sample_weights = weights[direction].reshape(-1, 1)
        d_direction = (forward["direction"] - one_hot) * sample_weights / rows
        d_regression = self.config.regression_weight * 2 * (forward["regression"] - regression) / rows
        d_volatility = self.config.volatility_weight * (forward["volatility"] - volatility) / rows

        grad_hidden = (d_direction @ self.w_direction.T
                       + d_regression @ self.w_regression.T
                       + d_volatility @ self.w_volatility.T)
        grad_pre = grad_hidden * (forward["pre"] > 0)

        rate = self.config.learning_rate
        self.w_direction -= rate * hidden.T @ d_direction
        self.b_direction -= rate * d_direction.sum(axis=0)
        self.w_regression -= rate * hidden.T @ d_regression
        self.b_regression -= rate * d_regression.sum(axis=0)
        self.w_volatility -= rate * hidden.T @ d_volatility
        self.b_volatility -= rate * d_volatility.sum(axis=0)
        self.w_trunk -= rate * matrix.T @ grad_pre
        self.b_trunk -= rate * grad_pre.sum(axis=0)

    def _loss(self, matrix, direction, regression, volatility, weights) -> float:
        forward = self._forward(matrix)
        probabilities = np.clip(forward["direction"], 1e-12, 1.0)
        picked = probabilities[np.arange(len(direction)), direction]
        cross_entropy = float(-(weights[direction] * np.log(picked)).mean())
        mse = float(((forward["regression"] - regression) ** 2).mean())
        volatility_loss = float(((forward["volatility"] - volatility) ** 2).mean())
        return (cross_entropy + self.config.regression_weight * mse
                + self.config.volatility_weight * volatility_loss)

    # ------------------------------------------------------------------ state
    def _state(self) -> dict[str, np.ndarray]:
        return {name: getattr(self, name).copy() for name in
                ("w_trunk", "b_trunk", "w_direction", "b_direction",
                 "w_regression", "b_regression", "w_volatility", "b_volatility")}

    def _restore(self, state: dict[str, np.ndarray]) -> None:
        for name, value in state.items():
            setattr(self, name, value.copy())

    def parameters(self) -> dict[str, list]:
        return {name: value.tolist() for name, value in self._state().items()}

    @classmethod
    def from_parameters(cls, input_units: int, config: MultiTaskConfig,
                        parameters: dict[str, Sequence]) -> "MultiTaskMLP":
        model = cls(input_units, config)
        for name, value in parameters.items():
            setattr(model, name, np.asarray(value, dtype=float))
        return model
