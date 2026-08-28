"""Drift monitoring.

Drift is FLAGGED, never acted on. Detecting drift does not retrain, does not
promote and does not demote — it raises a flag a human reads. Automatic
retrain-and-deploy is exactly the failure mode this module exists to prevent.

Population Stability Index is used for distribution comparison because it is
simple, interpretable, and has well-known thresholds (0.10 minor, 0.25 major).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence

import numpy as np

from config.settings import load_yaml


class DriftKind(StrEnum):
    FEATURE = "FEATURE"
    PREDICTION = "PREDICTION"
    PERFORMANCE = "PERFORMANCE"
    REGIME = "REGIME"
    DISTRIBUTION = "DISTRIBUTION"


class DriftSeverity(StrEnum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"


@dataclass(frozen=True, slots=True)
class DriftSignal:
    kind: DriftKind
    severity: DriftSeverity
    metric: float
    threshold: float
    detail: str
    flagged: bool
    # Deliberately constant: detection never triggers an action.
    action: str = "FLAG_ONLY"
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": str(self.kind), "severity": str(self.severity), "metric": self.metric,
                "threshold": self.threshold, "detail": self.detail, "flagged": self.flagged,
                "action": self.action, **self.context}


@dataclass(frozen=True, slots=True)
class DriftReport:
    signals: tuple[DriftSignal, ...]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def flagged(self) -> bool:
        return any(signal.flagged for signal in self.signals)

    @property
    def severity(self) -> DriftSeverity:
        order = {DriftSeverity.NONE: 0, DriftSeverity.MINOR: 1, DriftSeverity.MAJOR: 2}
        if not self.signals:
            return DriftSeverity.NONE
        return max((signal.severity for signal in self.signals), key=lambda item: order[item])

    def as_dict(self) -> dict[str, Any]:
        return {"flagged": self.flagged, "severity": str(self.severity),
                "timestamp": self.timestamp, "action": "FLAG_ONLY",
                "signals": [signal.as_dict() for signal in self.signals]}


def population_stability_index(reference: Sequence[float], current: Sequence[float], *,
                               bins: int = 10) -> float:
    """PSI between two samples. 0 means identical distributions."""
    reference = np.asarray([value for value in reference if value == value], dtype=float)
    current = np.asarray([value for value in current if value == value], dtype=float)
    if reference.size < 2 or current.size < 2:
        return 0.0
    edges = np.quantile(reference, np.linspace(0, 1, bins + 1))
    edges[0], edges[-1] = -np.inf, np.inf
    edges = np.unique(edges)
    if edges.size < 3:
        return 0.0
    reference_share = np.histogram(reference, bins=edges)[0] / reference.size
    current_share = np.histogram(current, bins=edges)[0] / current.size
    floor = 1e-6
    reference_share = np.clip(reference_share, floor, None)
    current_share = np.clip(current_share, floor, None)
    return float(np.sum((current_share - reference_share)
                        * np.log(current_share / reference_share)))


class DriftMonitor:
    def __init__(self, *, feature_threshold: float | None = None,
                 prediction_threshold: float | None = None,
                 performance_threshold: float | None = None):
        config = load_yaml().get("phase_13", {}).get("drift", {})
        self.feature_threshold = float(
            feature_threshold if feature_threshold is not None
            else config.get("feature_psi_threshold", 0.20))
        self.prediction_threshold = float(
            prediction_threshold if prediction_threshold is not None
            else config.get("prediction_psi_threshold", 0.15))
        self.performance_threshold = float(
            performance_threshold if performance_threshold is not None
            else config.get("performance_drop_threshold", 0.10))

    def _severity(self, metric: float, threshold: float) -> DriftSeverity:
        if metric >= threshold:
            return DriftSeverity.MAJOR
        if metric >= threshold / 2:
            return DriftSeverity.MINOR
        return DriftSeverity.NONE

    def feature_drift(self, reference: Mapping[str, Sequence[float]],
                      current: Mapping[str, Sequence[float]]) -> DriftSignal:
        scores = {name: population_stability_index(values, current.get(name, ()))
                  for name, values in reference.items() if name in current}
        worst_name = max(scores, key=scores.get) if scores else None
        worst = scores.get(worst_name, 0.0) if worst_name else 0.0
        severity = self._severity(worst, self.feature_threshold)
        return DriftSignal(
            DriftKind.FEATURE, severity, worst, self.feature_threshold,
            f"worst feature PSI: {worst_name}" if worst_name else "no comparable features",
            severity is DriftSeverity.MAJOR,
            context={"worst_feature": worst_name,
                     "top": dict(sorted(scores.items(), key=lambda item: item[1],
                                        reverse=True)[:5])})

    def prediction_drift(self, reference: Sequence[float],
                         current: Sequence[float]) -> DriftSignal:
        psi = population_stability_index(reference, current)
        severity = self._severity(psi, self.prediction_threshold)
        return DriftSignal(DriftKind.PREDICTION, severity, psi, self.prediction_threshold,
                           "prediction distribution PSI", severity is DriftSeverity.MAJOR)

    def performance_drift(self, baseline_score: float, current_score: float) -> DriftSignal:
        drop = float(baseline_score) - float(current_score)
        severity = self._severity(drop, self.performance_threshold)
        return DriftSignal(DriftKind.PERFORMANCE, severity, drop, self.performance_threshold,
                           "score drop against the validated baseline",
                           severity is DriftSeverity.MAJOR,
                           context={"baseline": baseline_score, "current": current_score})

    def regime_drift(self, reference: Mapping[str, int],
                     current: Mapping[str, int]) -> DriftSignal:
        """Compare regime mix; a model trained in a trend may be running in a range."""
        names = sorted(set(reference) | set(current))
        reference_total = sum(reference.values()) or 1
        current_total = sum(current.values()) or 1
        divergence = 0.0
        for name in names:
            expected = max(reference.get(name, 0) / reference_total, 1e-6)
            observed = max(current.get(name, 0) / current_total, 1e-6)
            divergence += (observed - expected) * np.log(observed / expected)
        severity = self._severity(float(divergence), self.feature_threshold)
        return DriftSignal(DriftKind.REGIME, severity, float(divergence),
                           self.feature_threshold, "regime mix divergence",
                           severity is DriftSeverity.MAJOR,
                           context={"reference": dict(reference), "current": dict(current)})

    def evaluate(self, *, reference_features: Mapping[str, Sequence[float]] | None = None,
                 current_features: Mapping[str, Sequence[float]] | None = None,
                 reference_predictions: Sequence[float] | None = None,
                 current_predictions: Sequence[float] | None = None,
                 baseline_score: float | None = None, current_score: float | None = None,
                 reference_regimes: Mapping[str, int] | None = None,
                 current_regimes: Mapping[str, int] | None = None) -> DriftReport:
        signals: list[DriftSignal] = []
        if reference_features and current_features:
            signals.append(self.feature_drift(reference_features, current_features))
        if reference_predictions is not None and current_predictions is not None:
            signals.append(self.prediction_drift(reference_predictions, current_predictions))
        if baseline_score is not None and current_score is not None:
            signals.append(self.performance_drift(baseline_score, current_score))
        if reference_regimes and current_regimes:
            signals.append(self.regime_drift(reference_regimes, current_regimes))
        return DriftReport(tuple(signals))
