from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from typing import Sequence


@dataclass(frozen=True, slots=True)
class SplitBoundary:
    name: str
    start_index: int
    end_index: int
    start_time: datetime
    end_time: datetime


@dataclass(frozen=True, slots=True)
class ChronologicalSplit:
    train: SplitBoundary
    validation: SplitBoundary
    test: SplitBoundary

    def name_for_index(self, index: int) -> str:
        if index <= self.train.end_index:
            return "TRAIN"
        if index <= self.validation.end_index:
            return "VALIDATION"
        return "TEST"


class ChronologicalSplitter:
    def __init__(self, *, train_ratio: float = 0.70, validation_ratio: float = 0.15):
        if train_ratio <= 0 or validation_ratio <= 0 or train_ratio + validation_ratio >= 1:
            raise ValueError("chronological split ratios must be positive and sum to less than one")
        self.train_ratio = train_ratio
        self.validation_ratio = validation_ratio

    def split(self, timestamps: Sequence[datetime]) -> ChronologicalSplit:
        if len(timestamps) < 3:
            raise ValueError("at least three samples are required for chronological split")
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("dataset timestamps must be strictly increasing")
        count = len(timestamps)
        train_end = max(0, int(count * self.train_ratio) - 1)
        validation_end = max(train_end + 1, int(count * (self.train_ratio + self.validation_ratio)) - 1)
        validation_end = min(validation_end, count - 2)
        return ChronologicalSplit(
            SplitBoundary("TRAIN", 0, train_end, timestamps[0], timestamps[train_end]),
            SplitBoundary("VALIDATION", train_end + 1, validation_end, timestamps[train_end + 1], timestamps[validation_end]),
            SplitBoundary("TEST", validation_end + 1, count - 1, timestamps[validation_end + 1], timestamps[-1]),
        )


@dataclass(frozen=True, slots=True)
class ScalerState:
    feature_names: tuple[str, ...]
    means: dict[str, float]
    standard_deviations: dict[str, float]
    fitted_split: str = "TRAIN"


class TrainOnlyStandardizer:
    """Fit once on TRAIN; the same immutable state transforms all three splits."""

    def fit(self, rows: Sequence[dict[str, float]], split: ChronologicalSplit) -> ScalerState:
        train_rows = rows[split.train.start_index:split.train.end_index + 1]
        if not train_rows:
            raise ValueError("TRAIN split is empty")
        names = tuple(sorted(train_rows[0]))
        if any(tuple(sorted(row)) != names for row in train_rows):
            raise ValueError("feature schema changed inside TRAIN split")
        means = {name: sum(row[name] for row in train_rows) / len(train_rows) for name in names}
        deviations = {}
        for name in names:
            variance = sum((row[name] - means[name]) ** 2 for row in train_rows) / len(train_rows)
            deviations[name] = sqrt(variance) or 1.0
        return ScalerState(names, means, deviations)

    @staticmethod
    def transform(rows: Sequence[dict[str, float]], state: ScalerState) -> list[dict[str, float]]:
        output = []
        for row in rows:
            if tuple(sorted(row)) != state.feature_names:
                raise ValueError("feature schema does not match fitted TRAIN scaler")
            output.append({
                name: (float(row[name]) - state.means[name]) / state.standard_deviations[name]
                for name in state.feature_names
            })
        return output
