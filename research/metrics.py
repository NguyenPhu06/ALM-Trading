"""Performance metrics for research (section 7).

Every metric is computed on **net** returns. Two conventions matter:

* Ratios that need a denominator return `None` when it does not exist — a
  strategy with no losing trades has no profit factor, and reporting `inf`
  invites a comparison that means nothing.
* Sharpe- and Sortino-*like* is deliberate in the naming. These are computed
  per observation, not annualised, because forward observations arrive at
  irregular intervals and an annualisation factor would be invented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from typing import Any, Sequence

from research.models import ResearchObservation


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    sample_size: int
    win_rate: float | None = None
    loss_rate: float | None = None
    expectancy: float | None = None
    net_pnl: float | None = None
    profit_factor: float | None = None
    average_win: float | None = None
    average_loss: float | None = None
    average_mae: float | None = None
    average_mfe: float | None = None
    worst_mae: float | None = None
    best_mfe: float | None = None
    maximum_drawdown: float | None = None
    return_over_drawdown: float | None = None
    sharpe_like: float | None = None
    sortino_like: float | None = None
    prediction_accuracy: float | None = None
    calibration: dict[str, Any] = field(default_factory=dict)
    tail_loss: float | None = None
    reliable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "sample_size": self.sample_size, "win_rate": self.win_rate,
            "loss_rate": self.loss_rate, "expectancy": self.expectancy,
            "net_pnl": self.net_pnl, "profit_factor": self.profit_factor,
            "average_win": self.average_win, "average_loss": self.average_loss,
            "average_mae": self.average_mae, "average_mfe": self.average_mfe,
            "worst_mae": self.worst_mae, "best_mfe": self.best_mfe,
            "maximum_drawdown": self.maximum_drawdown,
            "return_over_drawdown": self.return_over_drawdown,
            "sharpe_like": self.sharpe_like, "sortino_like": self.sortino_like,
            "prediction_accuracy": self.prediction_accuracy,
            "calibration": dict(self.calibration), "tail_loss": self.tail_loss,
            "reliable": self.reliable,
        }


EMPTY = PerformanceMetrics(sample_size=0)


def evaluate(observations: Sequence[ResearchObservation], *,
             minimum_samples: int = 30) -> PerformanceMetrics:
    rows = list(observations)
    if not rows:
        return EMPTY

    returns = [row.net_pnl for row in rows]
    wins = [value for value in returns if value > 0]
    losses = [value for value in returns if value < 0]
    gross_loss = abs(sum(losses))
    judged = [row for row in rows if row.correct is not None]
    maes = [row.mae for row in rows if row.mae is not None]
    mfes = [row.mfe for row in rows if row.mfe is not None]

    drawdown = max_drawdown(returns)
    total = sum(returns)

    return PerformanceMetrics(
        sample_size=len(rows),
        win_rate=len(wins) / len(rows),
        loss_rate=len(losses) / len(rows),
        expectancy=total / len(rows),
        net_pnl=total,
        profit_factor=(sum(wins) / gross_loss) if gross_loss else None,
        average_win=(sum(wins) / len(wins)) if wins else None,
        average_loss=(sum(losses) / len(losses)) if losses else None,
        average_mae=(sum(maes) / len(maes)) if maes else None,
        average_mfe=(sum(mfes) / len(mfes)) if mfes else None,
        worst_mae=min(maes) if maes else None,
        best_mfe=max(mfes) if mfes else None,
        maximum_drawdown=drawdown,
        return_over_drawdown=(total / drawdown) if drawdown else None,
        sharpe_like=sharpe_like(returns),
        sortino_like=sortino_like(returns),
        prediction_accuracy=(sum(1 for row in judged if row.correct) / len(judged)
                             if judged else None),
        calibration=calibration(rows),
        tail_loss=tail_loss(returns),
        reliable=len(rows) >= minimum_samples)


def max_drawdown(returns: Sequence[float]) -> float | None:
    """Peak-to-trough of the cumulative net equity path."""
    if not returns:
        return None
    equity = peak = worst = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def standard_deviation(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return sqrt(variance)


def sharpe_like(returns: Sequence[float]) -> float | None:
    """Mean over standard deviation, per observation. Not annualised — see module docstring."""
    deviation = standard_deviation(returns)
    if not deviation:
        return None
    return (sum(returns) / len(returns)) / deviation


def sortino_like(returns: Sequence[float]) -> float | None:
    """As above, but penalising only downside deviation."""
    downside = [value for value in returns if value < 0]
    if len(downside) < 2:
        return None
    deviation = sqrt(sum(value ** 2 for value in downside) / len(downside))
    if not deviation:
        return None
    return (sum(returns) / len(returns)) / deviation


def tail_loss(returns: Sequence[float], *, quantile: float = 0.05) -> float | None:
    """Mean of the worst `quantile` of outcomes — the DCA question in one number."""
    if not returns:
        return None
    ordered = sorted(returns)
    count = max(1, int(len(ordered) * quantile))
    tail = ordered[:count]
    return sum(tail) / len(tail)


def calibration(observations: Sequence[ResearchObservation], *,
                bins: int = 5) -> dict[str, Any]:
    """Brier score and expected calibration error against stated confidence."""
    rows = [row for row in observations
            if row.confidence is not None and row.correct is not None]
    if not rows:
        return {"samples": 0, "brier_score": None, "expected_calibration_error": None,
                "warning": "INSUFFICIENT_DATA_FOR_CALIBRATION"}

    brier = sum((row.confidence - (1.0 if row.correct else 0.0)) ** 2
                for row in rows) / len(rows)
    error = 0.0
    buckets = []
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        bucket = [row for row in rows
                  if low <= row.confidence < high
                  or (index == bins - 1 and row.confidence == 1.0)]
        if not bucket:
            continue
        mean_confidence = sum(row.confidence for row in bucket) / len(bucket)
        observed = sum(1 for row in bucket if row.correct) / len(bucket)
        error += (len(bucket) / len(rows)) * abs(mean_confidence - observed)
        buckets.append({"lower": low, "upper": high, "samples": len(bucket),
                        "mean_confidence": mean_confidence, "observed_accuracy": observed})
    return {"samples": len(rows), "brier_score": brier,
            "expected_calibration_error": error, "bins": buckets,
            "warning": "MODEL_CONFIDENCE_IS_UNCALIBRATED" if len(rows) < 30 else None}


def delta(left: PerformanceMetrics, right: PerformanceMetrics,
          names: Sequence[str] = ("expectancy", "win_rate", "maximum_drawdown",
                                  "average_mae", "average_mfe", "net_pnl",
                                  "profit_factor", "sharpe_like",
                                  "prediction_accuracy")) -> dict[str, float | None]:
    """right minus left, per metric. `None` where either side is missing."""
    result: dict[str, float | None] = {}
    for name in names:
        before = getattr(left, name, None)
        after = getattr(right, name, None)
        result[name] = (after - before) if (before is not None and after is not None) \
            else None
    before_error = (left.calibration or {}).get("brier_score")
    after_error = (right.calibration or {}).get("brier_score")
    result["calibration"] = (after_error - before_error) \
        if (before_error is not None and after_error is not None) else None
    return result
