from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from ai.evaluation.calibration import CalibrationReport, calibration_report
from ai.evaluation.metrics import ClassificationMetrics, classification_metrics
from ai.evaluation.trading_relevance import TradingRelevantMetrics, trading_relevant_metrics


@dataclass(frozen=True, slots=True)
class ModelEvaluation:
    model_version: str
    classification: ClassificationMetrics
    calibration: CalibrationReport
    trading_relevance: TradingRelevantMetrics


def evaluate_model(
    model_version: str, labels: np.ndarray, probabilities: np.ndarray,
    outcomes: Sequence[Mapping[str, object]], *, calibration_bins: int,
) -> ModelEvaluation:
    return ModelEvaluation(
        model_version, classification_metrics(labels, probabilities),
        calibration_report(labels, probabilities, bins=calibration_bins),
        trading_relevant_metrics(labels, probabilities, outcomes),
    )
