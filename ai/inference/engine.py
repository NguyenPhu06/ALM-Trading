from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

import numpy as np

from ai.features import HistoricalFeatureSchema
from ai.models import ModelInput, ModelPrediction, NumpyMLPClassifier, StructuredDecisionContext
from ai.models.registry import ModelRegistryMetadata
from features.intelligence import MarketIntelligenceSnapshot


@dataclass(frozen=True, slots=True)
class HistoricalPredictionOutcome:
    prediction: ModelPrediction
    observed_at: datetime
    future_return: float
    maximum_favorable_excursion: float
    maximum_adverse_excursion: float


class NeuralInferenceEngine:
    """Prediction-only boundary. No order, position, broker, or risk-bypass methods exist."""

    def __init__(self, model: NumpyMLPClassifier, metadata: ModelRegistryMetadata):
        self.model = model
        self.metadata = metadata
        if model.model_version != metadata.model_version:
            raise ValueError("loaded model and registry metadata versions differ")
        self.feature_names = tuple(metadata.scaler["feature_names"])
        if self.feature_names != metadata.features:
            raise ValueError("model registry features and scaler schema differ")

    def model_input(self, snapshot: MarketIntelligenceSnapshot) -> ModelInput:
        raw = HistoricalFeatureSchema.extract(snapshot)
        if snapshot.calculation_version != "phase3.v1":
            raise ValueError("unsupported market intelligence calculation version")
        if tuple(sorted(raw)) != tuple(sorted(self.feature_names)):
            raise ValueError("snapshot feature schema is incompatible with model")
        means = self.metadata.scaler["means"]
        deviations = self.metadata.scaler["standard_deviations"]
        values = tuple((float(raw[name]) - float(means[name])) / float(deviations[name]) for name in self.feature_names)
        return ModelInput(
            snapshot.timestamp, snapshot.symbol, values, self.feature_names,
            self.metadata.feature_version, self.metadata.dataset_version,
        )

    def predict(self, snapshot: MarketIntelligenceSnapshot) -> ModelPrediction:
        model_input = self.model_input(snapshot)
        probabilities = self.model.predict_proba(np.asarray([model_input.features], dtype=float))[0]
        return ModelPrediction(
            model_input.timestamp, model_input.symbol,
            float(probabilities[0]), float(probabilities[1]), float(probabilities[2]),
            float(np.max(probabilities)), self.metadata.model_version, self.metadata.feature_version,
        )

    def decision_context(
        self, snapshot: MarketIntelligenceSnapshot, *, rule_context: Mapping[str, Any],
        risk_context: Mapping[str, Any],
    ) -> StructuredDecisionContext:
        prediction = self.predict(snapshot)
        return StructuredDecisionContext(
            snapshot.timestamp, snapshot.symbol,
            {"higher_timeframe": snapshot.market_regime.get("higher_timeframe_bias"),
             "lower_timeframe": snapshot.market_regime.get("lower_timeframe_state"),
             "trade_state": snapshot.trade_state},
            rule_context, prediction, risk_context,
        )
