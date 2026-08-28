"""Rule-based baselines the neural network must beat.

If the network cannot beat a coin flip, the majority class, and a handful of
one-line indicator rules, it has no demonstrated value and must be marked
NO_EDGE. These are deliberately simple: a baseline that is hard to beat because
it is complicated proves nothing.

Each baseline consumes the same scaled feature matrix and emits three-class
probabilities, so they are directly comparable with the model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

CLASSES = ("UP", "DOWN", "NEUTRAL")
UP, DOWN, NEUTRAL = 0, 1, 2


def _one_hot(indices: Sequence[int], *, confidence: float = 0.6) -> np.ndarray:
    """Deliberately unconfident: a rule is a guess, not a calibrated probability."""
    spread = (1.0 - confidence) / 2.0
    output = np.full((len(indices), 3), spread, dtype=float)
    for row, index in enumerate(indices):
        output[row, index] = confidence
    return output


class BaseRuleBaseline:
    name = "baseline"

    def __init__(self, feature_names: Sequence[str]):
        self.feature_names = tuple(feature_names)
        self._index = {name: position for position, name in enumerate(self.feature_names)}

    def column(self, matrix: np.ndarray, name: str) -> np.ndarray | None:
        position = self._index.get(name)
        return matrix[:, position] if position is not None else None

    def fit(self, matrix: np.ndarray, labels: np.ndarray) -> "BaseRuleBaseline":
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        raise NotImplementedError


class RandomBaseline(BaseRuleBaseline):
    """Uniform guessing. Anything that cannot beat this is worthless."""

    name = "random"

    def __init__(self, feature_names: Sequence[str], *, seed: int = 42):
        super().__init__(feature_names)
        self.seed = seed

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        raw = rng.random((len(matrix), 3))
        return raw / raw.sum(axis=1, keepdims=True)


class MajorityBaseline(BaseRuleBaseline):
    """Always predicts the most common training class."""

    name = "majority"

    def __init__(self, feature_names: Sequence[str]):
        super().__init__(feature_names)
        self.distribution = np.array([1 / 3, 1 / 3, 1 / 3])

    def fit(self, matrix: np.ndarray, labels: np.ndarray) -> "MajorityBaseline":
        counts = np.bincount(np.asarray(labels, dtype=int), minlength=3).astype(float)
        total = counts.sum()
        self.distribution = counts / total if total else self.distribution
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        return np.tile(self.distribution, (len(matrix), 1))


class MomentumBaseline(BaseRuleBaseline):
    """Follow the M15 trend."""

    name = "momentum"

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        trend = self.column(matrix, "trend_m15")
        if trend is None:
            return MajorityBaseline(self.feature_names).predict_proba(matrix)
        return _one_hot([UP if value > 0 else DOWN if value < 0 else NEUTRAL
                         for value in trend])


class RegimeBaseline(BaseRuleBaseline):
    """Follow the higher-timeframe regime score."""

    name = "regime"

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        score = self.column(matrix, "htf_score")
        if score is None:
            return MajorityBaseline(self.feature_names).predict_proba(matrix)
        return _one_hot([UP if value > 0.1 else DOWN if value < -0.1 else NEUTRAL
                         for value in score])


class RSIBaseline(BaseRuleBaseline):
    """Classic mean reversion: oversold buys, overbought sells."""

    name = "rsi"

    def __init__(self, feature_names: Sequence[str], *, low: float = 30.0, high: float = 70.0):
        super().__init__(feature_names)
        self.low, self.high = low, high

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        rsi = self.column(matrix, "rsi_m15")
        if rsi is None:
            return MajorityBaseline(self.feature_names).predict_proba(matrix)
        return _one_hot([UP if value < self.low else DOWN if value > self.high else NEUTRAL
                         for value in rsi])


class IchimokuBaseline(BaseRuleBaseline):
    """Tenkan above Kijun is bullish, below is bearish."""

    name = "ichimoku"

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        cross = self.column(matrix, "ichimoku_cross_m15")
        if cross is None:
            return MajorityBaseline(self.feature_names).predict_proba(matrix)
        return _one_hot([UP if value > 0 else DOWN if value < 0 else NEUTRAL
                         for value in cross])


class ADXBaseline(BaseRuleBaseline):
    """Trade the trend only when ADX says a trend exists."""

    name = "adx"

    def __init__(self, feature_names: Sequence[str], *, threshold: float = 20.0):
        super().__init__(feature_names)
        self.threshold = threshold

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        adx = self.column(matrix, "adx_m15")
        trend = self.column(matrix, "trend_m15")
        if adx is None or trend is None:
            return MajorityBaseline(self.feature_names).predict_proba(matrix)
        picks = []
        for strength, direction in zip(adx, trend):
            if strength < self.threshold:
                picks.append(NEUTRAL)
            else:
                picks.append(UP if direction > 0 else DOWN if direction < 0 else NEUTRAL)
        return _one_hot(picks)


class CombinedRuleBaseline(BaseRuleBaseline):
    """Majority vote across the rule baselines."""

    name = "combined_rules"

    def __init__(self, feature_names: Sequence[str]):
        super().__init__(feature_names)
        self.members = [MomentumBaseline(feature_names), RegimeBaseline(feature_names),
                        RSIBaseline(feature_names), IchimokuBaseline(feature_names),
                        ADXBaseline(feature_names)]

    def fit(self, matrix: np.ndarray, labels: np.ndarray) -> "CombinedRuleBaseline":
        for member in self.members:
            member.fit(matrix, labels)
        return self

    def predict_proba(self, matrix: np.ndarray) -> np.ndarray:
        stacked = np.stack([member.predict_proba(matrix) for member in self.members])
        return stacked.mean(axis=0)


def all_baselines(feature_names: Sequence[str]) -> dict[str, BaseRuleBaseline]:
    return {baseline.name: baseline for baseline in (
        RandomBaseline(feature_names), MajorityBaseline(feature_names),
        MomentumBaseline(feature_names), RegimeBaseline(feature_names),
        RSIBaseline(feature_names), IchimokuBaseline(feature_names),
        ADXBaseline(feature_names), CombinedRuleBaseline(feature_names),
    )}
