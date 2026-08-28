"""Anomaly detection (section 21).

Nine things that should stay roughly the same, and an alert when one of them
does not. This is a *change* detector, not a quality detector: an anomaly says
the system is behaving differently from its own recent baseline, which is a
reason to look, not a verdict that something is wrong.

Everything is compared against a stated baseline. Without one there is no
anomaly, only a first observation — and the detector says so rather than treating
the first reading as normal or as alarming.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from statistics import fmean, pstdev
from typing import Any, Mapping, Sequence

from config.settings import load_yaml


class AnomalyKind(StrEnum):
    SIGNAL_FREQUENCY = "SIGNAL_FREQUENCY"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"
    ABNORMAL_SLIPPAGE = "ABNORMAL_SLIPPAGE"
    PREDICTION_DISTRIBUTION = "PREDICTION_DISTRIBUTION"
    CONFIDENCE_DISTRIBUTION = "CONFIDENCE_DISTRIBUTION"
    PNL_DISTRIBUTION = "PNL_DISTRIBUTION"
    REGIME_DISTRIBUTION = "REGIME_DISTRIBUTION"
    EXECUTION_LATENCY = "EXECUTION_LATENCY"
    MT5_CONNECTIVITY = "MT5_CONNECTIVITY"


NO_BASELINE = "NO_BASELINE"


@dataclass(frozen=True, slots=True)
class Anomaly:
    kind: AnomalyKind
    observed: Any
    baseline: Any
    change: float | None
    threshold: float
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": str(self.kind), "observed": self.observed, "baseline": self.baseline,
                "change": self.change, "threshold": self.threshold, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class AnomalyReport:
    anomalies: tuple[Anomaly, ...] = ()
    checked: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def detected(self) -> bool:
        return bool(self.anomalies)

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(str(anomaly.kind) for anomaly in self.anomalies)

    def as_dict(self) -> dict[str, Any]:
        return {"detected": self.detected,
                "anomalies": [anomaly.as_dict() for anomaly in self.anomalies],
                "kinds": list(self.kinds), "checked": list(self.checked),
                # A skipped check had no baseline; it is not a passed check.
                "skipped": list(self.skipped), "timestamp": self.timestamp}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _relative_change(observed: float, baseline: float) -> float:
    if baseline == 0:
        return float("inf") if observed else 0.0
    return abs(observed - baseline) / abs(baseline)


def _distribution_distance(observed: Mapping[str, Any],
                           baseline: Mapping[str, Any]) -> float:
    """Total variation distance between two categorical distributions.

    Half the sum of absolute differences in share, so the result is in [0, 1] and
    reads as "this fraction of the mass moved".
    """
    observed_total = sum(float(value) for value in observed.values()) or 1.0
    baseline_total = sum(float(value) for value in baseline.values()) or 1.0
    keys = set(observed) | set(baseline)
    return round(0.5 * sum(
        abs(float(observed.get(key, 0)) / observed_total
            - float(baseline.get(key, 0)) / baseline_total) for key in keys), 6)


class AnomalyDetector:
    """Compares a current window against a baseline window."""

    def __init__(self, *, frequency_threshold: float | None = None,
                 spread_threshold: float | None = None,
                 slippage_threshold: float | None = None,
                 distribution_threshold: float | None = None,
                 latency_threshold: float | None = None,
                 connectivity_threshold: float | None = None):
        config = load_yaml().get("phase_17", {}).get("anomaly", {})
        self.frequency_threshold = float(
            frequency_threshold if frequency_threshold is not None
            else config.get("frequency_threshold", 0.50))
        self.spread_threshold = float(
            spread_threshold if spread_threshold is not None
            else config.get("spread_threshold", 0.50))
        self.slippage_threshold = float(
            slippage_threshold if slippage_threshold is not None
            else config.get("slippage_threshold", 0.50))
        self.distribution_threshold = float(
            distribution_threshold if distribution_threshold is not None
            else config.get("distribution_threshold", 0.20))
        self.latency_threshold = float(
            latency_threshold if latency_threshold is not None
            else config.get("latency_threshold", 1.00))
        self.connectivity_threshold = float(
            connectivity_threshold if connectivity_threshold is not None
            else config.get("connectivity_threshold", 0.0))

    def detect(self, current: Mapping[str, Any],
               baseline: Mapping[str, Any] | None) -> AnomalyReport:
        """Compare the two windows. No baseline means nothing is anomalous yet."""
        if not baseline:
            return AnomalyReport((), (), tuple(str(kind) for kind in AnomalyKind))

        anomalies: list[Anomaly] = []
        checked: list[str] = []
        skipped: list[str] = []

        scalar_checks = (
            (AnomalyKind.SIGNAL_FREQUENCY, "signal_rate", self.frequency_threshold),
            (AnomalyKind.ABNORMAL_SPREAD, "spread", self.spread_threshold),
            (AnomalyKind.ABNORMAL_SLIPPAGE, "slippage", self.slippage_threshold),
            (AnomalyKind.EXECUTION_LATENCY, "latency_ms", self.latency_threshold),
        )
        for kind, key, threshold in scalar_checks:
            observed, expected = _number(current.get(key)), _number(baseline.get(key))
            if observed is None or expected is None:
                skipped.append(str(kind))
                continue
            checked.append(str(kind))
            change = _relative_change(observed, expected)
            if change > threshold:
                anomalies.append(Anomaly(kind, observed, expected, round(change, 6), threshold))

        distribution_checks = (
            (AnomalyKind.PREDICTION_DISTRIBUTION, "predictions"),
            (AnomalyKind.CONFIDENCE_DISTRIBUTION, "confidence_buckets"),
            (AnomalyKind.PNL_DISTRIBUTION, "pnl_buckets"),
            (AnomalyKind.REGIME_DISTRIBUTION, "regimes"),
        )
        for kind, key in distribution_checks:
            observed, expected = current.get(key), baseline.get(key)
            if not observed or not expected:
                skipped.append(str(kind))
                continue
            checked.append(str(kind))
            distance = _distribution_distance(observed, expected)
            if distance > self.distribution_threshold:
                anomalies.append(Anomaly(kind, dict(observed), dict(expected), distance,
                                         self.distribution_threshold))

        observed = _number(current.get("connection_failures"))
        expected = _number(baseline.get("connection_failures"))
        if observed is None or expected is None:
            skipped.append(str(AnomalyKind.MT5_CONNECTIVITY))
        else:
            checked.append(str(AnomalyKind.MT5_CONNECTIVITY))
            if observed > expected + self.connectivity_threshold:
                anomalies.append(Anomaly(
                    AnomalyKind.MT5_CONNECTIVITY, observed, expected,
                    round(observed - expected, 6), self.connectivity_threshold,
                    "more connection failures than the baseline window"))

        return AnomalyReport(tuple(anomalies), tuple(checked), tuple(skipped))

    @staticmethod
    def profile(rows: Sequence[Mapping[str, Any]], *, hours: float = 24.0) -> dict[str, Any]:
        """Reduce a population to the shape `detect` compares.

        `signal_rate` is per hour rather than a raw count, so a 24h window and a
        7d window are comparable without pretending they are the same size.
        """
        spreads = [value for value in (_number(row.get("spread")) for row in rows)
                   if value is not None]
        slips = [abs(value) for value in (_number(row.get("slippage")) for row in rows)
                 if value is not None]
        latencies = [value for value in (_number(row.get("latency_ms")) for row in rows)
                     if value is not None]
        pnls = [value for value in (_number(row.get("net_pnl")) for row in rows)
                if value is not None]

        predictions: dict[str, int] = {}
        regimes: dict[str, int] = {}
        confidence: dict[str, int] = {}
        pnl_buckets: dict[str, int] = {}
        for row in rows:
            side = str(row.get("side") or row.get("predicted") or "UNKNOWN").upper()
            predictions[side] = predictions.get(side, 0) + 1
            regime = str(row.get("regime") or "UNKNOWN").upper()
            regimes[regime] = regimes.get(regime, 0) + 1
            value = _number(row.get("confidence"))
            if value is not None:
                bucket = f"{int(min(value, 0.999) * 10) / 10:.1f}"
                confidence[bucket] = confidence.get(bucket, 0) + 1
            pnl = _number(row.get("net_pnl"))
            if pnl is not None:
                bucket = "WIN" if pnl > 0 else "LOSS" if pnl < 0 else "FLAT"
                pnl_buckets[bucket] = pnl_buckets.get(bucket, 0) + 1

        return {
            "samples": len(rows),
            "signal_rate": round(len(rows) / hours, 6) if hours else None,
            "spread": round(fmean(spreads), 8) if spreads else None,
            "slippage": round(fmean(slips), 8) if slips else None,
            "latency_ms": round(fmean(latencies), 3) if latencies else None,
            "pnl_stdev": round(pstdev(pnls), 8) if len(pnls) > 1 else None,
            "predictions": predictions, "regimes": regimes,
            "confidence_buckets": confidence, "pnl_buckets": pnl_buckets,
            "connection_failures": sum(int(row.get("connection_failure") or 0) for row in rows),
        }
