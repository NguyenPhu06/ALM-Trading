from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


CLASS_NAMES = ("UP", "DOWN", "NEUTRAL")
CLASS_TO_INDEX = {name: index for index, name in enumerate(CLASS_NAMES)}


@dataclass(frozen=True, slots=True)
class ClassImbalanceReport:
    counts: dict[str, int]
    distribution: dict[str, float]
    imbalanced: bool
    class_weights: dict[str, float]


def analyze_class_imbalance(labels: Sequence[int], *, maximum_class_share: float = 0.60) -> ClassImbalanceReport:
    values = np.asarray(labels, dtype=int)
    counts = {name: int(np.sum(values == index)) for index, name in enumerate(CLASS_NAMES)}
    total = max(1, len(values))
    distribution = {name: count / total for name, count in counts.items()}
    present = sum(count > 0 for count in counts.values())
    weights = {
        name: (total / (present * count) if count else 0.0)
        for name, count in counts.items()
    }
    return ClassImbalanceReport(
        counts, distribution,
        any(value > maximum_class_share for value in distribution.values()) or present < len(CLASS_NAMES),
        weights,
    )
