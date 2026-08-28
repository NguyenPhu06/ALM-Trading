"""Statistical significance for research (section 15).

Four things are reported for every comparison, and an edge is only claimed when
all four agree: sample size, a confidence interval that excludes zero, an effect
size that is not negligible, and stability across walk-forward windows.

Effect size is included because a statistically significant difference can still
be economically meaningless — with enough samples, anything separates.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import sqrt
from typing import Any, Sequence

import numpy as np

from ai.evaluation.significance import bootstrap_interval, period_stability
from config.settings import load_yaml
from research.metrics import standard_deviation


class SignificanceVerdict(StrEnum):
    SIGNIFICANT = "SIGNIFICANT"
    NOT_SIGNIFICANT = "NOT_SIGNIFICANT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNSTABLE = "UNSTABLE"


# Cohen's conventions, used only to name a magnitude — not to bless it.
EFFECT_BANDS = ((0.80, "LARGE"), (0.50, "MEDIUM"), (0.20, "SMALL"))


def effect_size(left: Sequence[float], right: Sequence[float]) -> float | None:
    """Cohen's d with a pooled standard deviation. `None` when it cannot be formed."""
    if len(left) < 2 or len(right) < 2:
        return None
    left_deviation = standard_deviation(left)
    right_deviation = standard_deviation(right)
    if left_deviation is None or right_deviation is None:
        return None
    pooled = sqrt((((len(left) - 1) * left_deviation ** 2)
                   + ((len(right) - 1) * right_deviation ** 2))
                  / (len(left) + len(right) - 2))
    if not pooled:
        return None
    return ((sum(right) / len(right)) - (sum(left) / len(left))) / pooled


def band(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    magnitude = abs(value)
    for threshold, name in EFFECT_BANDS:
        if magnitude >= threshold:
            return name
    return "NEGLIGIBLE"


def difference_interval(left: Sequence[float], right: Sequence[float], *,
                        samples: int = 1000, level: float = 0.95,
                        seed: int = 42) -> dict[str, Any]:
    """Bootstrap interval for the difference in means (right - left)."""
    if not left or not right:
        return {"lower": None, "upper": None, "level": level, "excludes_zero": False}
    generator = np.random.default_rng(seed)
    left_values = np.asarray(left, dtype=float)
    right_values = np.asarray(right, dtype=float)
    differences = []
    for _ in range(int(samples)):
        a = generator.choice(left_values, size=len(left_values), replace=True)
        b = generator.choice(right_values, size=len(right_values), replace=True)
        differences.append(float(b.mean() - a.mean()))
    tail = (1.0 - level) / 2.0
    lower = float(np.quantile(differences, tail))
    upper = float(np.quantile(differences, 1.0 - tail))
    return {"lower": lower, "upper": upper, "level": level,
            "excludes_zero": lower > 0 or upper < 0}


@dataclass(frozen=True, slots=True)
class SignificanceReport:
    verdict: SignificanceVerdict
    sample_size: int
    baseline_size: int = 0
    difference: float | None = None
    effect_size: float | None = None
    effect_band: str = "UNKNOWN"
    confidence_interval: dict[str, Any] = field(default_factory=dict)
    bootstrap_interval: dict[str, Any] = field(default_factory=dict)
    stability: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()

    @property
    def significant(self) -> bool:
        return self.verdict is SignificanceVerdict.SIGNIFICANT

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": str(self.verdict), "significant": self.significant,
                "sample_size": self.sample_size, "baseline_size": self.baseline_size,
                "difference": self.difference, "effect_size": self.effect_size,
                "effect_band": self.effect_band,
                "confidence_interval": dict(self.confidence_interval),
                "bootstrap_interval": dict(self.bootstrap_interval),
                "stability": dict(self.stability), "reasons": list(self.reasons)}


class SignificanceTester:
    def __init__(self, *, minimum_samples: int | None = None,
                 minimum_effect: float = 0.20, confidence_level: float | None = None,
                 bootstrap_samples: int | None = None, periods: int = 3):
        config = load_yaml().get("phase_15", {})
        phase13 = load_yaml().get("phase_13", {})
        self.minimum_samples = int(minimum_samples if minimum_samples is not None
                                   else config.get("minimum_samples",
                                                   phase13.get("minimum_samples_for_edge",
                                                               100)))
        self.minimum_effect = float(minimum_effect)
        self.confidence_level = float(confidence_level if confidence_level is not None
                                      else phase13.get("confidence_level", 0.95))
        self.bootstrap_samples = int(bootstrap_samples if bootstrap_samples is not None
                                     else phase13.get("bootstrap_samples", 1000))
        self.periods = int(periods)

    def absolute(self, returns: Sequence[float], *, seed: int = 42) -> SignificanceReport:
        """Is this series distinguishable from zero, and stable while it is?"""
        values = [float(value) for value in returns]
        if len(values) < self.minimum_samples:
            return SignificanceReport(
                SignificanceVerdict.INSUFFICIENT_DATA, len(values),
                reasons=(f"SAMPLE_BELOW_MINIMUM_{self.minimum_samples}",))

        interval = bootstrap_interval(values, samples=self.bootstrap_samples,
                                      level=self.confidence_level, seed=seed)
        stability = period_stability(values, periods=self.periods)
        mean = sum(values) / len(values)

        reasons: list[str] = []
        if not interval.excludes_zero:
            reasons.append("CONFIDENCE_INTERVAL_INCLUDES_ZERO")
        if reasons:
            return SignificanceReport(
                SignificanceVerdict.NOT_SIGNIFICANT, len(values), difference=mean,
                confidence_interval=interval.as_dict(), stability=stability,
                reasons=tuple(reasons))
        if not stability.get("consistent_sign", False):
            return SignificanceReport(
                SignificanceVerdict.UNSTABLE, len(values), difference=mean,
                confidence_interval=interval.as_dict(), stability=stability,
                reasons=("PERIOD_SIGN_FLIPS",))
        return SignificanceReport(
            SignificanceVerdict.SIGNIFICANT, len(values), difference=mean,
            confidence_interval=interval.as_dict(), stability=stability)

    def compare(self, baseline: Sequence[float], candidate: Sequence[float], *,
                seed: int = 42) -> SignificanceReport:
        """Is `candidate` distinguishable from `baseline`, and by enough to matter?"""
        left = [float(value) for value in baseline]
        right = [float(value) for value in candidate]

        if len(right) < self.minimum_samples or len(left) < self.minimum_samples:
            return SignificanceReport(
                SignificanceVerdict.INSUFFICIENT_DATA, len(right), len(left),
                reasons=(f"SAMPLE_BELOW_MINIMUM_{self.minimum_samples}",))

        difference = (sum(right) / len(right)) - (sum(left) / len(left))
        size = effect_size(left, right)
        interval = difference_interval(left, right, samples=self.bootstrap_samples,
                                       level=self.confidence_level, seed=seed)
        stability = period_stability([b - a for a, b in
                                      zip(left, right)] if len(left) == len(right)
                                     else right, periods=self.periods)

        reasons: list[str] = []
        if not interval["excludes_zero"]:
            reasons.append("DIFFERENCE_INTERVAL_INCLUDES_ZERO")
        if size is None:
            # No pooled deviation means no magnitude to judge — most often a
            # degenerate, zero-variance arm. Refuse rather than let a bootstrap
            # over constants read as a decisive result.
            reasons.append("EFFECT_SIZE_UNAVAILABLE")
        elif abs(size) < self.minimum_effect:
            # Statistically separable, economically indistinguishable.
            reasons.append(f"EFFECT_BELOW_{self.minimum_effect}")

        verdict = (SignificanceVerdict.SIGNIFICANT if not reasons
                   else SignificanceVerdict.NOT_SIGNIFICANT)
        return SignificanceReport(
            verdict, len(right), len(left), difference=difference, effect_size=size,
            effect_band=band(size), bootstrap_interval=interval, stability=stability,
            reasons=tuple(reasons))
