"""Permutation importance by feature group.

Importance here means "shuffling this group degrades the model's score by X".
That is an association measured on held-out data, **not** a causal claim: the
report says `association`, never `cause`, and `disclaimer` states it plainly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from ai.dataset.features import FEATURE_GROUPS, FeatureExtractor

DISCLAIMER = ("Permutation importance measures association between a feature group and "
              "model score on held-out data. It does not establish causality, and it "
              "does not explain the market.")


@dataclass(frozen=True, slots=True)
class GroupImportance:
    group: str
    features: int
    baseline_score: float
    permuted_score: float
    importance: float
    relative: float

    def as_dict(self) -> dict[str, Any]:
        return {"group": self.group, "features": self.features,
                "baseline_score": self.baseline_score, "permuted_score": self.permuted_score,
                "importance": self.importance, "relative": self.relative}


@dataclass(frozen=True, slots=True)
class ExplainabilityReport:
    baseline_score: float
    groups: tuple[GroupImportance, ...]
    metric: str = "accuracy"
    disclaimer: str = DISCLAIMER

    @property
    def ranked(self) -> tuple[GroupImportance, ...]:
        return tuple(sorted(self.groups, key=lambda item: item.importance, reverse=True))

    @property
    def most_influential(self) -> str | None:
        ranked = self.ranked
        return ranked[0].group if ranked else None

    def as_dict(self) -> dict[str, Any]:
        return {"baseline_score": self.baseline_score, "metric": self.metric,
                "most_influential": self.most_influential,
                "groups": [item.as_dict() for item in self.ranked],
                "disclaimer": self.disclaimer}


def accuracy_score(labels: np.ndarray, probabilities: np.ndarray) -> float:
    if not len(labels):
        return 0.0
    return float((probabilities.argmax(axis=1) == labels).mean())


class PermutationImportance:
    """Group-level permutation importance, computed on held-out data only."""

    def __init__(self, *, repeats: int = 5, seed: int = 42,
                 scorer: Callable[[np.ndarray, np.ndarray], float] = accuracy_score):
        self.repeats = int(repeats)
        self.seed = int(seed)
        self.scorer = scorer

    def explain(self, predict_proba: Callable[[np.ndarray], np.ndarray], matrix: np.ndarray,
                labels: Sequence[int], feature_names: Sequence[str]) -> ExplainabilityReport:
        matrix = np.asarray(matrix, dtype=float)
        labels = np.asarray(labels, dtype=int)
        if matrix.size == 0:
            return ExplainabilityReport(0.0, ())

        baseline = self.scorer(labels, predict_proba(matrix))
        grouped = FeatureExtractor.grouped(feature_names)
        positions = {name: index for index, name in enumerate(feature_names)}
        rng = np.random.default_rng(self.seed)

        results: list[GroupImportance] = []
        for group, names in grouped.items():
            columns = [positions[name] for name in names if name in positions]
            if not columns:
                continue
            scores = []
            for _ in range(self.repeats):
                shuffled = matrix.copy()
                order = rng.permutation(len(shuffled))
                shuffled[:, columns] = shuffled[order][:, columns]
                scores.append(self.scorer(labels, predict_proba(shuffled)))
            permuted = float(np.mean(scores))
            importance = baseline - permuted
            results.append(GroupImportance(
                group, len(columns), baseline, permuted, importance,
                importance / baseline if baseline else 0.0))
        return ExplainabilityReport(baseline, tuple(results))
