"""Online inference for the multi-task model.

Inference only. There is no `fit` on this class and no path from here to training:
learning happens in `ai.training.forward_trainer`, run as an explicit job.

The engine emits probabilities and expectations plus a threshold verdict. The
verdict is advisory — it says whether the model's own confidence bar was met, not
whether to trade. Structure, liquidity, session, risk, spread, DCA rules and the
execution guard all still apply, and only the Strategy Engine decides.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import numpy as np

from ai.dataset.features import FeatureExtractor
from ai.models.multitask import MultiTaskMLP, MultiTaskOutput
from config.settings import load_yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConfidenceThresholds:
    """Configurable, never hardcoded. Validate these out-of-sample before trusting them."""

    minimum_confidence: float = 0.55
    minimum_probability: float = 0.55
    minimum_expected_return: float = 0.0005
    maximum_expected_mae: float = 0.0030

    @classmethod
    def from_config(cls) -> "ConfidenceThresholds":
        config = load_yaml().get("phase_13", {}).get("thresholds", {})
        return cls(
            minimum_confidence=float(config.get("minimum_confidence", 0.55)),
            minimum_probability=float(config.get("minimum_probability", 0.55)),
            minimum_expected_return=float(config.get("minimum_expected_return", 0.0005)),
            maximum_expected_mae=float(config.get("maximum_expected_mae", 0.0030)),
        )

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class InferenceResult:
    timestamp: datetime
    symbol: str
    direction_probability: dict[str, float]
    expected_return: float
    expected_mfe: float
    expected_mae: float
    volatility_probability: float
    confidence: float
    model_version: str
    feature_version: str
    model_id: str | None = None
    meets_thresholds: bool = False
    threshold_reasons: tuple[str, ...] = ()
    thresholds: dict[str, Any] = field(default_factory=dict)

    @property
    def predicted_class(self) -> str:
        return max(self.direction_probability, key=self.direction_probability.get)

    @property
    def prob_up(self) -> float:
        return self.direction_probability.get("UP", 0.0)

    @property
    def prob_down(self) -> float:
        return self.direction_probability.get("DOWN", 0.0)

    @property
    def prob_neutral(self) -> float:
        return self.direction_probability.get("NEUTRAL", 0.0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp, "symbol": self.symbol,
            "direction_probability": dict(self.direction_probability),
            "prob_up": self.prob_up, "prob_down": self.prob_down,
            "prob_neutral": self.prob_neutral, "predicted_class": self.predicted_class,
            "expected_return": self.expected_return, "expected_mfe": self.expected_mfe,
            "expected_mae": self.expected_mae,
            "volatility_probability": self.volatility_probability,
            "confidence": self.confidence, "model_version": self.model_version,
            "feature_version": self.feature_version, "model_id": self.model_id,
            "meets_thresholds": self.meets_thresholds,
            "threshold_reasons": list(self.threshold_reasons),
            "thresholds": dict(self.thresholds),
            # Stated so no consumer can mistake this for an instruction.
            "is_trade_instruction": False,
        }


class MultiTaskInferenceEngine:
    """Wraps a trained model plus its scaler. Read-only with respect to the model."""

    def __init__(self, model: MultiTaskMLP, *, feature_names: Sequence[str],
                 means: Mapping[str, float], deviations: Mapping[str, float],
                 model_version: str, feature_version: str, model_id: str | None = None,
                 thresholds: ConfidenceThresholds | None = None,
                 extractor: FeatureExtractor | None = None):
        self.model = model
        self.feature_names = tuple(feature_names)
        self.means = dict(means)
        self.deviations = dict(deviations)
        self.model_version = model_version
        self.feature_version = feature_version
        self.model_id = model_id
        self.thresholds = thresholds or ConfidenceThresholds.from_config()
        self.extractor = extractor or FeatureExtractor()

    # `fit` is deliberately absent: see module docstring.

    def _vector(self, mapping: Mapping[str, float]) -> np.ndarray:
        row = []
        for name in self.feature_names:
            value = float(mapping.get(name, 0.0))
            mean = self.means.get(name, 0.0)
            deviation = self.deviations.get(name) or 1.0
            row.append((value - mean) / deviation)
        return np.asarray([row], dtype=float)

    def predict_snapshot(self, snapshot: Mapping[str, Any]) -> InferenceResult:
        feature_row = self.extractor.extract(snapshot)
        if feature_row.feature_version != self.feature_version:
            raise ValueError(
                f"feature version mismatch: snapshot {feature_row.feature_version} "
                f"vs model {self.feature_version}")
        output = self.model.predict(self._vector(feature_row.as_mapping()))[0]
        timestamp = feature_row.timestamp or datetime.now(timezone.utc)
        return self._result(output, timestamp, feature_row.symbol)

    def _result(self, output: MultiTaskOutput, timestamp: datetime,
                symbol: str) -> InferenceResult:
        meets, reasons = self.evaluate_thresholds(output)
        return InferenceResult(
            timestamp=timestamp, symbol=symbol,
            direction_probability=dict(output.direction_probability),
            expected_return=output.expected_return, expected_mfe=output.expected_mfe,
            expected_mae=output.expected_mae,
            volatility_probability=output.volatility_probability,
            confidence=output.confidence, model_version=self.model_version,
            feature_version=self.feature_version, model_id=self.model_id,
            meets_thresholds=meets, threshold_reasons=reasons,
            thresholds=self.thresholds.as_dict())

    def evaluate_thresholds(self, output: MultiTaskOutput) -> tuple[bool, tuple[str, ...]]:
        """Advisory only: the strategy still applies every other gate."""
        reasons: list[str] = []
        limits = self.thresholds
        if output.confidence < limits.minimum_confidence:
            reasons.append("CONFIDENCE_BELOW_MINIMUM")
        best = max(output.direction_probability.values())
        if best < limits.minimum_probability:
            reasons.append("PROBABILITY_BELOW_MINIMUM")
        if output.predicted_class == "NEUTRAL":
            reasons.append("PREDICTED_NEUTRAL")
        elif abs(output.expected_return) < limits.minimum_expected_return:
            reasons.append("EXPECTED_RETURN_BELOW_MINIMUM")
        if abs(output.expected_mae) > limits.maximum_expected_mae:
            reasons.append("EXPECTED_MAE_ABOVE_MAXIMUM")
        return (not reasons), tuple(reasons)

    @classmethod
    def from_artifact(cls, artifact: Mapping[str, Any], *,
                      thresholds: ConfidenceThresholds | None = None
                      ) -> "MultiTaskInferenceEngine":
        from ai.models.multitask import MultiTaskConfig

        config = MultiTaskConfig(**artifact.get("config", {}))
        feature_names = tuple(artifact["feature_names"])
        model = MultiTaskMLP.from_parameters(len(feature_names), config,
                                             artifact["parameters"])
        return cls(model, feature_names=feature_names, means=artifact["means"],
                   deviations=artifact["deviations"],
                   model_version=artifact.get("model_version", MultiTaskMLP.ARCHITECTURE_VERSION),
                   feature_version=artifact.get("feature_version", "features_v1"),
                   model_id=artifact.get("model_id"), thresholds=thresholds)
