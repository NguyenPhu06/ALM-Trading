from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Sequence


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    window: int
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime


class ExpandingWalkForward:
    """Produces expanding TRAIN windows followed by untouched validation and test windows."""

    def __init__(self, *, initial_train_size: int, validation_size: int, test_size: int, step_size: int | None = None):
        if min(initial_train_size, validation_size, test_size) < 1:
            raise ValueError("walk-forward window sizes must be positive")
        self.initial_train_size = initial_train_size
        self.validation_size = validation_size
        self.test_size = test_size
        self.step_size = step_size or test_size

    def windows(self, timestamps: Sequence[datetime]) -> Iterator[WalkForwardWindow]:
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            raise ValueError("walk-forward timestamps must be strictly increasing")
        train_end = self.initial_train_size - 1
        number = 1
        while train_end + self.validation_size + self.test_size < len(timestamps):
            validation_start = train_end + 1
            validation_end = validation_start + self.validation_size - 1
            test_start = validation_end + 1
            test_end = test_start + self.test_size - 1
            yield WalkForwardWindow(
                number, timestamps[0], timestamps[train_end], timestamps[validation_start],
                timestamps[validation_end], timestamps[test_start], timestamps[test_end],
            )
            number += 1
            train_end += self.step_size
