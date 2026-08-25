from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ai.training.imbalance import CLASS_NAMES


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    lower: float
    upper: float
    samples: int
    mean_probability: float
    observed_frequency: float


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    bins_by_class: dict[str, tuple[CalibrationBin, ...]]
    expected_calibration_error: dict[str, float]
    warning: str = "MODEL_CONFIDENCE_IS_UNCALIBRATED"


def calibration_report(labels: np.ndarray, probabilities: np.ndarray, *, bins: int) -> CalibrationReport:
    if bins < 2:
        raise ValueError("calibration requires at least two bins")
    boundaries = np.linspace(0.0, 1.0, bins + 1)
    reports = {}
    errors = {}
    for class_index, name in enumerate(CLASS_NAMES):
        class_bins = []
        weighted_error = 0.0
        actual = labels == class_index
        values = probabilities[:, class_index]
        for index in range(bins):
            lower, upper = float(boundaries[index]), float(boundaries[index + 1])
            selected = (values >= lower) & ((values < upper) if index < bins - 1 else (values <= upper))
            count = int(np.sum(selected))
            if not count:
                continue
            mean_probability = float(np.mean(values[selected]))
            observed = float(np.mean(actual[selected]))
            weighted_error += count / len(values) * abs(mean_probability - observed)
            class_bins.append(CalibrationBin(lower, upper, count, mean_probability, observed))
        reports[name] = tuple(class_bins)
        errors[name] = weighted_error
    return CalibrationReport(reports, errors)
