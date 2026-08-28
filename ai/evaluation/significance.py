"""Statistical significance and the NO_EDGE verdict.

An edge claimed from forty observations is not an edge. This module refuses to
return EDGE_DETECTED below a configured sample size, and otherwise requires a
bootstrap confidence interval for mean return that excludes zero.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Sequence

import numpy as np

from config.settings import load_yaml


class EdgeVerdict(StrEnum):
    EDGE_DETECTED = "EDGE_DETECTED"
    NO_EDGE = "NO_EDGE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: float
    upper: float
    level: float

    @property
    def excludes_zero(self) -> bool:
        return self.lower > 0 or self.upper < 0

    def as_dict(self) -> dict[str, Any]:
        return {"lower": self.lower, "upper": self.upper, "level": self.level,
                "excludes_zero": self.excludes_zero}


@dataclass(frozen=True, slots=True)
class SignificanceReport:
    verdict: EdgeVerdict
    samples: int
    mean_return: float | None
    median_return: float | None
    win_rate: float | None
    expectancy: float | None
    max_drawdown: float | None
    interval: ConfidenceInterval | None
    stability: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    @property
    def edge(self) -> bool:
        return self.verdict is EdgeVerdict.EDGE_DETECTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict), "edge": self.edge, "samples": self.samples,
            "mean_return": self.mean_return, "median_return": self.median_return,
            "win_rate": self.win_rate, "expectancy": self.expectancy,
            "max_drawdown": self.max_drawdown,
            "confidence_interval": self.interval.as_dict() if self.interval else None,
            "stability": dict(self.stability), "reasons": list(self.reasons),
        }


def bootstrap_interval(values: Sequence[float], *, samples: int = 1000,
                       level: float = 0.95, seed: int = 42) -> ConfidenceInterval | None:
    data = np.asarray([float(value) for value in values], dtype=float)
    if data.size < 2:
        return None
    rng = np.random.default_rng(seed)
    means = np.empty(samples, dtype=float)
    for index in range(samples):
        draw = rng.choice(data, size=data.size, replace=True)
        means[index] = draw.mean()
    tail = (1.0 - level) / 2.0
    return ConfidenceInterval(float(np.quantile(means, tail)),
                              float(np.quantile(means, 1.0 - tail)), level)


def period_stability(values: Sequence[float], *, periods: int = 3) -> dict[str, Any]:
    """Split the series chronologically and report the sign of each period's mean."""
    data = [float(value) for value in values]
    if len(data) < periods:
        return {"periods": 0, "means": [], "consistent_sign": False}
    size = len(data) // periods
    means = [float(np.mean(data[index * size:(index + 1) * size])) for index in range(periods)]
    signs = {mean > 0 for mean in means}
    return {"periods": periods, "means": means, "consistent_sign": len(signs) == 1}


class SignificanceEvaluator:
    def __init__(self, *, minimum_samples: int | None = None,
                 bootstrap_samples: int | None = None, level: float | None = None):
        config = load_yaml().get("phase_13", {})
        self.minimum_samples = int(minimum_samples if minimum_samples is not None
                                   else config.get("minimum_samples_for_edge", 100))
        self.bootstrap_samples = int(bootstrap_samples if bootstrap_samples is not None
                                     else config.get("bootstrap_samples", 1000))
        self.level = float(level if level is not None else config.get("confidence_level", 0.95))

    def evaluate(self, returns: Sequence[float], *, seed: int = 42) -> SignificanceReport:
        data = [float(value) for value in returns if value is not None]
        reasons: list[str] = []

        if len(data) < self.minimum_samples:
            reasons.append(f"SAMPLE_BELOW_MINIMUM_{self.minimum_samples}")
            interval = bootstrap_interval(data, samples=self.bootstrap_samples,
                                          level=self.level, seed=seed) if len(data) >= 2 else None
            return SignificanceReport(
                EdgeVerdict.INSUFFICIENT_DATA, len(data),
                float(np.mean(data)) if data else None,
                float(np.median(data)) if data else None,
                (sum(1 for value in data if value > 0) / len(data)) if data else None,
                float(np.mean(data)) if data else None,
                self._drawdown(data), interval, period_stability(data), tuple(reasons))

        interval = bootstrap_interval(data, samples=self.bootstrap_samples,
                                      level=self.level, seed=seed)
        stability = period_stability(data)
        mean = float(np.mean(data))

        if interval is None or not interval.excludes_zero:
            reasons.append("CONFIDENCE_INTERVAL_INCLUDES_ZERO")
        if mean <= 0:
            reasons.append("MEAN_RETURN_NOT_POSITIVE")
        if not stability["consistent_sign"]:
            reasons.append("UNSTABLE_ACROSS_PERIODS")

        verdict = EdgeVerdict.NO_EDGE if reasons else EdgeVerdict.EDGE_DETECTED
        return SignificanceReport(
            verdict, len(data), mean, float(np.median(data)),
            sum(1 for value in data if value > 0) / len(data), mean,
            self._drawdown(data), interval, stability, tuple(reasons))

    @staticmethod
    def _drawdown(values: Sequence[float]) -> float | None:
        if not values:
            return None
        equity = np.cumsum(np.asarray(values, dtype=float))
        peak = np.maximum.accumulate(equity)
        return float((peak - equity).max())
