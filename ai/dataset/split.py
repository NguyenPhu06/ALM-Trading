"""Chronological splitting for Phase 13.

Delegates to the Phase 4 implementation in `ai.datasets.split` so there is one
splitter in the codebase, and adds the guard rail Phase 13 asks for: a helper
that refuses a random split outright rather than offering one.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from ai.datasets.split import (
    ChronologicalSplit,
    ChronologicalSplitter,
    ScalerState,
    SplitBoundary,
    TrainOnlyStandardizer,
)
from config.settings import load_yaml

__all__ = [
    "ChronologicalSplit", "ChronologicalSplitter", "ScalerState", "SplitBoundary",
    "TrainOnlyStandardizer", "RandomSplitRefused", "build_splitter", "split_bounds",
]


class RandomSplitRefused(RuntimeError):
    """Raised if anything asks for a shuffled split of a market time series."""


def random_split(*args: Any, **kwargs: Any):
    """Present so the mistake fails loudly instead of being reinvented locally."""
    raise RandomSplitRefused(
        "market time series must never be split randomly; use ChronologicalSplitter")


def build_splitter(*, train_ratio: float | None = None,
                   validation_ratio: float | None = None) -> ChronologicalSplitter:
    config = load_yaml().get("phase_13", {}).get("split", {})
    return ChronologicalSplitter(
        train_ratio=float(train_ratio if train_ratio is not None
                          else config.get("train_ratio", 0.70)),
        validation_ratio=float(validation_ratio if validation_ratio is not None
                               else config.get("validation_ratio", 0.15)),
    )


def split_bounds(split: ChronologicalSplit) -> dict[str, tuple[datetime, datetime]]:
    """First and last timestamp of each partition, for the leakage checker."""
    return {name: (boundary.start_time, boundary.end_time)
            for name, boundary in (("train", split.train),
                                   ("validation", split.validation),
                                   ("test", split.test))}
