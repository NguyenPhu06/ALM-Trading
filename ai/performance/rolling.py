"""Rolling forward performance (section 14).

Five windows — 7, 14, 30, 60 and 90 days — computed only where enough data
exists. A window below the sample floor reports `reliable = False` and keeps its
numbers visible rather than hiding them: seeing "0.71 win rate over 4 trades,
not reliable" is more useful than seeing nothing, as long as nothing downstream
treats it as evidence.

All PnL figures are net of cost. Calibration is measured against the model's own
stated confidence, because a model that is 85% confident and 50% right is the
failure this section exists to surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence

WINDOWS: tuple[int, ...] = (7, 14, 30, 60, 90)
CALIBRATION_BINS = 5


@dataclass(frozen=True, slots=True)
class PerformanceEntry:
    """One resolved observation, reduced to what performance needs."""

    observation_id: str
    resolved_at: datetime
    net_pnl: float
    mae: float | None = None
    mfe: float | None = None
    correct: bool | None = None
    confidence: float | None = None
    spread: float | None = None
    regime: str | None = None
    session: str | None = None
    timeframe: str | None = None

    @classmethod
    def from_pair(cls, observation: Any, outcome: Any,
                  analysis: Any = None) -> "PerformanceEntry":
        correct = getattr(analysis, "correct", None)
        return cls(
            observation_id=str(_read(outcome, "observation_id")
                               or _read(observation, "observation_id") or ""),
            resolved_at=_read(outcome, "resolved_at"),
            net_pnl=float(_read(outcome, "net_hypothetical_pnl") or 0.0),
            mae=_number(_read(outcome, "mae")), mfe=_number(_read(outcome, "mfe")),
            correct=correct, confidence=_number(_read(observation, "nn_confidence")),
            spread=_number(_read(outcome, "spread")),
            regime=_text(_read(observation, "market_regime")),
            session=_text(_read(observation, "session")),
            timeframe=_text(_read(observation, "timeframe")))


@dataclass(frozen=True, slots=True)
class RollingMetrics:
    days: int
    samples: int
    reliable: bool
    win_rate: float | None = None
    expectancy: float | None = None
    profit_factor: float | None = None
    average_mae: float | None = None
    average_mfe: float | None = None
    net_pnl: float | None = None
    max_drawdown: float | None = None
    prediction_accuracy: float | None = None
    calibration: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"days": self.days, "samples": self.samples, "reliable": self.reliable,
                "win_rate": self.win_rate, "expectancy": self.expectancy,
                "profit_factor": self.profit_factor, "average_mae": self.average_mae,
                "average_mfe": self.average_mfe, "net_pnl": self.net_pnl,
                "max_drawdown": self.max_drawdown,
                "prediction_accuracy": self.prediction_accuracy,
                "calibration": dict(self.calibration)}


class RollingPerformance:
    def __init__(self, *, windows: Sequence[int] = WINDOWS, minimum_samples: int = 20):
        self.windows = tuple(int(day) for day in windows)
        self.minimum_samples = int(minimum_samples)

    def evaluate(self, entries: Sequence[PerformanceEntry], *,
                 now: datetime) -> dict[str, RollingMetrics]:
        rows = [entry for entry in entries if entry.resolved_at is not None]
        return {f"{days}d": self._window(rows, days, now) for days in self.windows}

    def _window(self, entries: Sequence[PerformanceEntry], days: int,
                now: datetime) -> RollingMetrics:
        cutoff = now - timedelta(days=days)
        rows = sorted((entry for entry in entries if entry.resolved_at >= cutoff),
                      key=lambda entry: entry.resolved_at)
        if not rows:
            return RollingMetrics(days, 0, False)

        returns = [entry.net_pnl for entry in rows]
        wins = [value for value in returns if value > 0]
        losses = [value for value in returns if value < 0]
        gross_loss = abs(sum(losses))
        judged = [entry for entry in rows if entry.correct is not None]

        maes = [entry.mae for entry in rows if entry.mae is not None]
        mfes = [entry.mfe for entry in rows if entry.mfe is not None]

        return RollingMetrics(
            days=days, samples=len(rows), reliable=len(rows) >= self.minimum_samples,
            win_rate=len(wins) / len(rows),
            expectancy=sum(returns) / len(returns),
            profit_factor=(sum(wins) / gross_loss) if gross_loss else None,
            average_mae=(sum(maes) / len(maes)) if maes else None,
            average_mfe=(sum(mfes) / len(mfes)) if mfes else None,
            net_pnl=sum(returns),
            max_drawdown=_max_drawdown(returns),
            prediction_accuracy=(sum(1 for entry in judged if entry.correct) / len(judged)
                                 if judged else None),
            calibration=calibration_report(judged))

    def summary(self, entries: Sequence[PerformanceEntry], *,
                now: datetime) -> dict[str, Any]:
        windows = self.evaluate(entries, now=now)
        reliable = [name for name, metrics in windows.items() if metrics.reliable]
        return {"windows": {name: metrics.as_dict() for name, metrics in windows.items()},
                "reliable_windows": reliable, "minimum_samples": self.minimum_samples,
                "total_samples": len(entries)}


def calibration_report(entries: Sequence[PerformanceEntry]) -> dict[str, Any]:
    """Brier score and expected calibration error against stated confidence."""
    rows = [entry for entry in entries
            if entry.confidence is not None and entry.correct is not None]
    if not rows:
        return {"samples": 0, "brier_score": None, "expected_calibration_error": None,
                "bins": [], "warning": "INSUFFICIENT_DATA_FOR_CALIBRATION"}

    brier = sum((entry.confidence - (1.0 if entry.correct else 0.0)) ** 2
                for entry in rows) / len(rows)

    bins: list[dict[str, Any]] = []
    error = 0.0
    for index in range(CALIBRATION_BINS):
        low = index / CALIBRATION_BINS
        high = (index + 1) / CALIBRATION_BINS
        bucket = [entry for entry in rows
                  if low <= entry.confidence < high
                  or (index == CALIBRATION_BINS - 1 and entry.confidence == 1.0)]
        if not bucket:
            continue
        mean_confidence = sum(entry.confidence for entry in bucket) / len(bucket)
        observed = sum(1 for entry in bucket if entry.correct) / len(bucket)
        error += (len(bucket) / len(rows)) * abs(mean_confidence - observed)
        bins.append({"lower": low, "upper": high, "samples": len(bucket),
                     "mean_confidence": mean_confidence, "observed_accuracy": observed})

    warning = None
    if len(rows) < 30:
        warning = "MODEL_CONFIDENCE_IS_UNCALIBRATED"
    return {"samples": len(rows), "brier_score": brier,
            "expected_calibration_error": error, "bins": bins, "warning": warning}


def _max_drawdown(returns: Sequence[float]) -> float | None:
    if not returns:
        return None
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def _read(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return str(value) if value is not None else None
