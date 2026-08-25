from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ModelInput:
    timestamp: datetime
    symbol: str
    features: tuple[float, ...]
    feature_names: tuple[str, ...]
    feature_version: str
    dataset_version: str

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("ModelInput timestamp must be timezone-aware")
        if len(self.features) != len(self.feature_names):
            raise ValueError("model input feature names and values are misaligned")
        forbidden = {"label", "classification", "future_return", "mfe", "mae"}
        if any(any(token in name.lower() for token in forbidden) for name in self.feature_names):
            raise ValueError("labels or future outcomes cannot enter ModelInput")


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    timestamp: datetime
    symbol: str
    prob_up: float
    prob_down: float
    prob_neutral: float
    confidence: float
    model_version: str
    feature_version: str

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("ModelPrediction timestamp must be timezone-aware")
        probabilities = (self.prob_up, self.prob_down, self.prob_neutral)
        if any(value < 0.0 or value > 1.0 for value in probabilities):
            raise ValueError("prediction probabilities must be in [0, 1]")
        if abs(sum(probabilities) - 1.0) > 1e-6:
            raise ValueError("prediction probabilities must sum to one")
        if abs(self.confidence - max(probabilities)) > 1e-6:
            raise ValueError("confidence must equal the maximum uncalibrated class probability")

    @property
    def predicted_class(self) -> str:
        values = {"UP": self.prob_up, "DOWN": self.prob_down, "NEUTRAL": self.prob_neutral}
        return max(values, key=values.get)


@dataclass(frozen=True, slots=True)
class StructuredDecisionContext:
    timestamp: datetime
    symbol: str
    market_context: Mapping[str, object]
    rule_context: Mapping[str, object]
    prediction: ModelPrediction
    risk_context: Mapping[str, object]
    action: None = None

    def __post_init__(self) -> None:
        if self.action is not None:
            raise ValueError("Phase 5 decision context cannot contain a trading action")
