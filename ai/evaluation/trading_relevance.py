from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Mapping, Sequence

import numpy as np

from ai.training.imbalance import CLASS_NAMES


@dataclass(frozen=True, slots=True)
class TradingRelevantMetrics:
    prediction_hit_rate: float
    conditional_future_return: dict[str, float | None]
    conditional_mfe: dict[str, float | None]
    conditional_mae: dict[str, float | None]
    disclaimer: str = "RESEARCH_ASSOCIATION_NOT_STRATEGY_PROFITABILITY"


def trading_relevant_metrics(
    labels: np.ndarray, probabilities: np.ndarray, outcomes: Sequence[Mapping[str, object]],
) -> TradingRelevantMetrics:
    predictions = np.argmax(probabilities, axis=1)
    if len(outcomes) != len(predictions):
        raise ValueError("historical outcomes must align with predictions")
    grouped_returns = {name: [] for name in CLASS_NAMES}
    grouped_mfe = {name: [] for name in CLASS_NAMES}
    grouped_mae = {name: [] for name in CLASS_NAMES}
    for prediction, outcome in zip(predictions, outcomes):
        name = CLASS_NAMES[int(prediction)]
        grouped_returns[name].append(float(outcome["future_return_5"]))
        grouped_mfe[name].append(float(outcome["maximum_favorable_excursion"]))
        grouped_mae[name].append(float(outcome["maximum_adverse_excursion"]))
    average = lambda values: mean(values) if values else None
    return TradingRelevantMetrics(
        float(np.mean(predictions == labels)),
        {name: average(values) for name, values in grouped_returns.items()},
        {name: average(values) for name, values in grouped_mfe.items()},
        {name: average(values) for name, values in grouped_mae.items()},
    )
