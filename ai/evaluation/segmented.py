"""Metrics broken out by regime, session and timeframe.

A model that works in STRONG_BULL and fails in RANGE is not a working model, and
an aggregate score hides exactly that. Every segment reports its own sample size
so a flattering number from twelve observations is visibly untrustworthy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from ai.evaluation.metrics import classification_metrics

REGIMES = ("STRONG_BULL", "BULL", "RANGE", "BEAR", "STRONG_BEAR", "UNKNOWN")
SESSIONS = ("ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP", "OFF_SESSION")
TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")


@dataclass(frozen=True, slots=True)
class SegmentMetrics:
    segment: str
    samples: int
    accuracy: float | None = None
    balanced_accuracy: float | None = None
    log_loss: float | None = None
    brier: float | None = None
    expectancy: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    average_win: float | None = None
    average_loss: float | None = None
    max_drawdown: float | None = None
    mean_return: float | None = None
    reliable: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(frozen=True, slots=True)
class SegmentedReport:
    dimension: str
    segments: dict[str, SegmentMetrics] = field(default_factory=dict)
    minimum_samples: int = 30

    @property
    def reliable_segments(self) -> tuple[str, ...]:
        return tuple(name for name, item in self.segments.items() if item.reliable)

    @property
    def weakest(self) -> SegmentMetrics | None:
        candidates = [item for item in self.segments.values()
                      if item.reliable and item.expectancy is not None]
        return min(candidates, key=lambda item: item.expectancy) if candidates else None

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "minimum_samples": self.minimum_samples,
                "reliable_segments": list(self.reliable_segments),
                "segments": {name: item.as_dict() for name, item in self.segments.items()}}


def trading_metrics(returns: Sequence[float]) -> dict[str, float | None]:
    """Expectancy, win rate, profit factor and drawdown from a return series."""
    values = [float(value) for value in returns if value is not None]
    if not values:
        return {"expectancy": None, "win_rate": None, "profit_factor": None,
                "average_win": None, "average_loss": None, "max_drawdown": None,
                "mean_return": None}
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))

    equity = np.cumsum(values)
    peak = np.maximum.accumulate(equity)
    drawdown = float((peak - equity).max()) if len(equity) else 0.0

    return {
        "expectancy": float(np.mean(values)),
        "win_rate": len(wins) / len(values),
        "profit_factor": (gross_profit / gross_loss) if gross_loss else
                         (float("inf") if gross_profit else None),
        "average_win": float(np.mean(wins)) if wins else 0.0,
        "average_loss": float(np.mean(losses)) if losses else 0.0,
        "max_drawdown": drawdown,
        "mean_return": float(np.mean(values)),
    }


class SegmentedEvaluator:
    def __init__(self, *, minimum_samples: int = 30):
        self.minimum_samples = int(minimum_samples)

    def evaluate(self, *, labels: Sequence[int], probabilities: Sequence[Sequence[float]],
                 returns: Sequence[float], segments: Sequence[str],
                 dimension: str, universe: Sequence[str] | None = None) -> SegmentedReport:
        labels = np.asarray(labels, dtype=int)
        probabilities = np.asarray(probabilities, dtype=float)
        returns = np.asarray(returns, dtype=float)
        segments = [str(item) for item in segments]

        names = list(universe) if universe else sorted(set(segments))
        results: dict[str, SegmentMetrics] = {}
        for name in names:
            mask = np.asarray([item == name for item in segments], dtype=bool)
            count = int(mask.sum())
            if count == 0:
                results[name] = SegmentMetrics(name, 0)
                continue
            trading = trading_metrics(returns[mask].tolist())
            accuracy = balanced = log_loss = brier = None
            if probabilities.size:
                try:
                    metrics = classification_metrics(labels[mask], probabilities[mask])
                    payload = metrics.as_dict()
                    accuracy = payload.get("accuracy")
                    balanced = payload.get("balanced_accuracy")
                    log_loss = payload.get("log_loss")
                    brier = payload.get("brier_score")
                except Exception:
                    # A segment with a single class cannot produce every metric;
                    # report what is computable rather than dropping the segment.
                    accuracy = float((labels[mask] == probabilities[mask].argmax(axis=1)).mean())
            results[name] = SegmentMetrics(
                name, count, accuracy, balanced, log_loss, brier,
                trading["expectancy"], trading["win_rate"], trading["profit_factor"],
                trading["average_win"], trading["average_loss"], trading["max_drawdown"],
                trading["mean_return"], reliable=count >= self.minimum_samples)
        return SegmentedReport(dimension, results, self.minimum_samples)

    def by_regime(self, **kwargs: Any) -> SegmentedReport:
        return self.evaluate(dimension="regime", universe=REGIMES, **kwargs)

    def by_session(self, **kwargs: Any) -> SegmentedReport:
        return self.evaluate(dimension="session", universe=SESSIONS, **kwargs)

    def by_timeframe(self, **kwargs: Any) -> SegmentedReport:
        return self.evaluate(dimension="timeframe", universe=TIMEFRAMES, **kwargs)
