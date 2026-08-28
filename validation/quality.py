"""Execution, signal and model quality (sections 7, 8 and 9).

Three different questions, deliberately reported side by side:

* **Execution quality** — did the broker do what we asked, and at what cost?
* **Signal quality** — were the decisions any good?
* **Model quality** — was the network right, and was it right for the right reason?

A strategy with a positive expectancy and a 40% rejection rate is not working. A
network with 60% accuracy that is confidently wrong is more dangerous than one
with 52% accuracy that knows it. Reporting these together is what makes those
statements visible instead of averaged away.

Every figure carries its sample size and `reliable` stays false until there is
enough of it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import fmean, pstdev
from typing import Any, Sequence

from config.settings import load_yaml

MINIMUM_SAMPLES = 30


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _percentiles(values: Sequence[float]) -> dict[str, float | None]:
    """p50/p90/p99 without numpy, on a copy, nearest-rank."""
    rows = sorted(values)
    if not rows:
        return {"p50": None, "p90": None, "p99": None, "min": None, "max": None}
    def at(fraction: float) -> float:
        index = min(len(rows) - 1, max(0, round(fraction * len(rows)) - 1))
        return round(rows[index], 8)
    return {"p50": at(0.50), "p90": at(0.90), "p99": at(0.99),
            "min": round(rows[0], 8), "max": round(rows[-1], 8)}


# ------------------------------------------------------------------ section 7
@dataclass(frozen=True, slots=True)
class ExecutionQuality:
    submitted: int
    filled: int
    partially_filled: int
    rejected: int
    errored: int
    fill_rate: float | None
    rejection_rate: float | None
    average_slippage: float | None
    worst_slippage: float | None
    spread_distribution: dict[str, float | None] = field(default_factory=dict)
    latency_ms: dict[str, float | None] = field(default_factory=dict)
    reconciliation_failures: int = 0
    connection_failures: int = 0
    reliable: bool = False
    reasons: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "submitted": self.submitted, "filled": self.filled,
            "partially_filled": self.partially_filled, "rejected": self.rejected,
            "errored": self.errored, "fill_rate": self.fill_rate,
            "rejection_rate": self.rejection_rate, "average_slippage": self.average_slippage,
            "worst_slippage": self.worst_slippage,
            "spread_distribution": dict(self.spread_distribution),
            "latency_ms": dict(self.latency_ms),
            "reconciliation_failures": self.reconciliation_failures,
            "connection_failures": self.connection_failures,
            "reliable": self.reliable, "reasons": list(self.reasons),
            "timestamp": self.timestamp,
        }


def calculate_execution_quality(records: Sequence[Any], *, reconciliation_failures: int = 0,
                                connection_failures: int = 0,
                                minimum_samples: int = MINIMUM_SAMPLES) -> ExecutionQuality:
    """Aggregate per-order execution records.

    A record is any mapping with `status`, and optionally `slippage`, `spread`
    and `latency_ms`. Missing figures are excluded rather than counted as zero:
    an unmeasured latency is not a fast one.
    """
    rows = [row if isinstance(row, dict) else
            (row.as_dict() if hasattr(row, "as_dict") else dict(row)) for row in records]
    submitted = len(rows)
    statuses = [str(row.get("status") or "").upper() for row in rows]
    filled = statuses.count("FILLED")
    partial = statuses.count("PARTIAL") + statuses.count("PARTIALLY_FILLED")
    rejected = statuses.count("REJECTED") + statuses.count("BLOCKED")
    errored = statuses.count("FAILED") + statuses.count("ERROR")

    slips = [abs(value) for value in (_number(row.get("slippage")) for row in rows)
             if value is not None]
    spreads = [value for value in (_number(row.get("spread")) for row in rows)
               if value is not None]
    latencies = [value for value in (_number(row.get("latency_ms")) for row in rows)
                 if value is not None]

    reasons = () if submitted >= minimum_samples else ("INSUFFICIENT_SAMPLES",)
    return ExecutionQuality(
        submitted=submitted, filled=filled, partially_filled=partial, rejected=rejected,
        errored=errored,
        fill_rate=round((filled + partial) / submitted, 4) if submitted else None,
        rejection_rate=round(rejected / submitted, 4) if submitted else None,
        average_slippage=round(fmean(slips), 8) if slips else None,
        worst_slippage=round(max(slips), 8) if slips else None,
        spread_distribution=_percentiles(spreads),
        latency_ms=_percentiles(latencies),
        reconciliation_failures=reconciliation_failures,
        connection_failures=connection_failures,
        reliable=submitted >= minimum_samples and not reasons,
        reasons=reasons)


# ------------------------------------------------------------------ section 8
@dataclass(frozen=True, slots=True)
class SignalQuality:
    signals: int
    buy: int
    sell: int
    neutral: int
    resolved: int
    wins: int
    losses: int
    win_rate: float | None
    expectancy: float | None
    profit_factor: float | None
    net_pnl: float
    mae: float | None
    mfe: float | None
    drawdown: float
    reliable: bool = False
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "signals": self.signals, "buy": self.buy, "sell": self.sell,
            "neutral": self.neutral, "resolved": self.resolved, "wins": self.wins,
            "losses": self.losses, "win_rate": self.win_rate, "expectancy": self.expectancy,
            "profit_factor": self.profit_factor, "net_pnl": round(self.net_pnl, 8),
            "mae": self.mae, "mfe": self.mfe, "drawdown": round(self.drawdown, 8),
            "reliable": self.reliable, "reasons": list(self.reasons),
        }


def calculate_signal_quality(signals: Sequence[Any], outcomes: Sequence[Any] = (), *,
                             minimum_samples: int = MINIMUM_SAMPLES) -> SignalQuality:
    """Counts from the signals, performance from the resolved outcomes.

    Unresolved signals are counted as signals and excluded from performance. They
    are neither wins nor losses, and treating them as flat would quietly improve
    every figure below.
    """
    sides = [str(getattr(signal, "side", "") or "").upper() for signal in signals]
    buy = sum(side in {"BUY", "LONG"} for side in sides)
    sell = sum(side in {"SELL", "SHORT"} for side in sides)
    neutral = len(sides) - buy - sell

    pnls = [value for value in
            (_number(getattr(outcome, "net_expected_pnl", None)) for outcome in outcomes)
            if value is not None]
    maes = [value for value in (_number(getattr(outcome, "mae", None)) for outcome in outcomes)
            if value is not None]
    mfes = [value for value in (_number(getattr(outcome, "mfe", None)) for outcome in outcomes)
            if value is not None]

    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    gain, pain = sum(wins), abs(sum(losses))
    equity = peak = drawdown = 0.0
    for value in pnls:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)

    reasons = () if len(pnls) >= minimum_samples else ("INSUFFICIENT_SAMPLES",)
    return SignalQuality(
        signals=len(sides), buy=buy, sell=sell, neutral=neutral, resolved=len(pnls),
        wins=len(wins), losses=len(losses),
        win_rate=round(len(wins) / len(pnls), 4) if pnls else None,
        expectancy=round(fmean(pnls), 8) if pnls else None,
        profit_factor=round(gain / pain, 4) if pain else None,
        net_pnl=sum(pnls),
        mae=round(fmean(maes), 8) if maes else None,
        mfe=round(fmean(mfes), 8) if mfes else None,
        drawdown=drawdown, reliable=len(pnls) >= minimum_samples, reasons=reasons)


# ------------------------------------------------------------------ section 9
@dataclass(frozen=True, slots=True)
class ModelQuality:
    samples: int
    accuracy: float | None
    mean_confidence: float | None
    calibration_gap: float | None
    calibration_quality: float | None
    high_confidence_failures: int
    high_confidence_failure_rate: float | None
    false_bullish: int
    false_bearish: int
    false_neutral: int
    prediction_drift: float | None = None
    confidence_drift: float | None = None
    model_drift: bool = False
    reliable: bool = False
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples, "accuracy": self.accuracy,
            "mean_confidence": self.mean_confidence, "calibration_gap": self.calibration_gap,
            "calibration_quality": self.calibration_quality,
            "high_confidence_failures": self.high_confidence_failures,
            "high_confidence_failure_rate": self.high_confidence_failure_rate,
            "false_bullish": self.false_bullish, "false_bearish": self.false_bearish,
            "false_neutral": self.false_neutral, "prediction_drift": self.prediction_drift,
            "confidence_drift": self.confidence_drift, "model_drift": self.model_drift,
            "reliable": self.reliable, "reasons": list(self.reasons),
        }


def _direction(value: Any) -> str:
    text = str(value or "").upper()
    if text in {"BUY", "LONG", "UP", "BULLISH"}:
        return "UP"
    if text in {"SELL", "SHORT", "DOWN", "BEARISH"}:
        return "DOWN"
    return "NEUTRAL"


def calculate_model_quality(predictions: Sequence[Any], *,
                            high_confidence_threshold: float | None = None,
                            calibration_gap_threshold: float | None = None,
                            baseline: Sequence[Any] = (),
                            minimum_samples: int = MINIMUM_SAMPLES) -> ModelQuality:
    """Score the network against what actually happened.

    Each row needs `predicted` (UP/DOWN/NEUTRAL or a side), `actual` and
    `confidence`. Rows missing any of the three are excluded: an unscored
    prediction is not a correct one.

    `calibration_gap` is mean confidence minus observed accuracy. A positive gap
    is overconfidence, which is the direction that costs money.
    """
    config = load_yaml().get("phase_14", {})
    threshold = float(high_confidence_threshold if high_confidence_threshold is not None
                      else config.get("high_confidence_threshold", 0.75))
    gap_threshold = float(calibration_gap_threshold if calibration_gap_threshold is not None
                          else config.get("calibration_gap_threshold", 0.20))

    rows = []
    for row in predictions:
        payload = row if isinstance(row, dict) else (
            row.as_dict() if hasattr(row, "as_dict") else dict(row))
        predicted, actual = payload.get("predicted"), payload.get("actual")
        confidence = _number(payload.get("confidence"))
        if predicted is None or actual is None or confidence is None:
            continue
        rows.append((_direction(predicted), _direction(actual), confidence))

    if not rows:
        return ModelQuality(0, None, None, None, None, 0, None, 0, 0, 0,
                            reliable=False, reasons=("NO_SCORED_PREDICTIONS",))

    correct = [predicted == actual for predicted, actual, _ in rows]
    confidences = [confidence for _, _, confidence in rows]
    accuracy = sum(correct) / len(rows)
    mean_confidence = fmean(confidences)
    gap = mean_confidence - accuracy

    high_confidence_failures = sum(
        1 for (predicted, actual, confidence) in rows
        if confidence >= threshold and predicted != actual)
    high_confidence_total = sum(1 for (_, _, confidence) in rows if confidence >= threshold)

    false_bullish = sum(1 for predicted, actual, _ in rows
                        if predicted == "UP" and actual != "UP")
    false_bearish = sum(1 for predicted, actual, _ in rows
                        if predicted == "DOWN" and actual != "DOWN")
    false_neutral = sum(1 for predicted, actual, _ in rows
                        if predicted == "NEUTRAL" and actual != "NEUTRAL")

    prediction_drift = confidence_drift = None
    if baseline:
        base_rows = []
        for row in baseline:
            payload = row if isinstance(row, dict) else (
                row.as_dict() if hasattr(row, "as_dict") else dict(row))
            value = _number(payload.get("confidence"))
            if value is not None:
                base_rows.append((_direction(payload.get("predicted")), value))
        if base_rows:
            base_up = sum(1 for direction, _ in base_rows if direction == "UP") / len(base_rows)
            now_up = sum(1 for predicted, _, _ in rows if predicted == "UP") / len(rows)
            prediction_drift = round(abs(now_up - base_up), 6)
            confidence_drift = round(
                abs(mean_confidence - fmean([value for _, value in base_rows])), 6)

    reasons: list[str] = []
    if len(rows) < minimum_samples:
        reasons.append("INSUFFICIENT_SAMPLES")
    if gap > gap_threshold:
        reasons.append("OVERCONFIDENT")

    return ModelQuality(
        samples=len(rows), accuracy=round(accuracy, 4),
        mean_confidence=round(mean_confidence, 4), calibration_gap=round(gap, 4),
        # 1 - |gap|, clamped: a perfectly calibrated model scores 1.
        calibration_quality=round(max(0.0, 1.0 - abs(gap)), 4),
        high_confidence_failures=high_confidence_failures,
        high_confidence_failure_rate=(round(high_confidence_failures / high_confidence_total, 4)
                                      if high_confidence_total else None),
        false_bullish=false_bullish, false_bearish=false_bearish, false_neutral=false_neutral,
        prediction_drift=prediction_drift, confidence_drift=confidence_drift,
        model_drift=bool(prediction_drift and prediction_drift > 0.20),
        reliable=len(rows) >= minimum_samples, reasons=tuple(reasons))
