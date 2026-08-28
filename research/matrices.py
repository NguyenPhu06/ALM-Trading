"""Performance matrices (sections 8, 9, 10 and 18).

One machine, three slicing dimensions, because the mistake is identical in all
three: reading an aggregate and assuming it holds everywhere.

Every cell reports its own sample size and carries a `reliable` flag. A cell
below the floor is still printed — hiding it would make a sparse matrix look
like a complete one — but nothing downstream may treat it as evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from config.settings import load_yaml
from research.metrics import PerformanceMetrics, evaluate
from research.models import (
    REGIMES,
    SESSIONS,
    TIMEFRAMES,
    ResearchObservation,
    require_forward_only,
    segment,
)

# Section 8's columns, in order.
MATRIX_COLUMNS = ("sample_size", "win_rate", "expectancy", "net_pnl",
                  "maximum_drawdown", "average_mae", "average_mfe")

# Section 9 names the four active sessions; OFF_SESSION and CUSTOM are reported
# too so nothing is silently dropped.
ACTIVE_SESSIONS = ("ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP")


@dataclass(frozen=True, slots=True)
class MatrixCell:
    name: str
    metrics: PerformanceMetrics

    @property
    def reliable(self) -> bool:
        return self.metrics.reliable

    def row(self) -> dict[str, Any]:
        payload = self.metrics.as_dict()
        return {"name": self.name, "reliable": self.reliable,
                **{column: payload.get(column) for column in MATRIX_COLUMNS}}

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "reliable": self.reliable,
                "metrics": self.metrics.as_dict()}


@dataclass(frozen=True, slots=True)
class Matrix:
    dimension: str
    cells: dict[str, MatrixCell]
    minimum_samples: int
    columns: tuple[str, ...] = MATRIX_COLUMNS

    @property
    def reliable_cells(self) -> tuple[str, ...]:
        return tuple(name for name, cell in sorted(self.cells.items()) if cell.reliable)

    @property
    def best(self) -> str | None:
        """Best by expectancy among cells that are actually reliable."""
        scored = [(name, cell.metrics.expectancy) for name, cell in self.cells.items()
                  if cell.reliable and cell.metrics.expectancy is not None]
        return max(scored, key=lambda item: item[1])[0] if scored else None

    @property
    def worst(self) -> str | None:
        scored = [(name, cell.metrics.expectancy) for name, cell in self.cells.items()
                  if cell.reliable and cell.metrics.expectancy is not None]
        return min(scored, key=lambda item: item[1])[0] if scored else None

    @property
    def profitable(self) -> tuple[str, ...]:
        return tuple(name for name, cell in sorted(self.cells.items())
                     if cell.reliable and (cell.metrics.expectancy or 0) > 0)

    @property
    def losing(self) -> tuple[str, ...]:
        return tuple(name for name, cell in sorted(self.cells.items())
                     if cell.reliable and (cell.metrics.expectancy or 0) <= 0)

    def rows(self) -> list[dict[str, Any]]:
        return [self.cells[name].row() for name in sorted(self.cells)]

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "minimum_samples": self.minimum_samples,
                "columns": list(self.columns), "best": self.best, "worst": self.worst,
                "profitable": list(self.profitable), "losing": list(self.losing),
                "reliable_cells": list(self.reliable_cells),
                "rows": self.rows(),
                "cells": {name: cell.as_dict() for name, cell in sorted(self.cells.items())}}


class MatrixBuilder:
    def __init__(self, *, minimum_samples: int | None = None):
        config = load_yaml().get("phase_15", {})
        self.minimum_samples = int(minimum_samples if minimum_samples is not None
                                   else config.get("matrix_minimum_samples", 30))

    def build(self, observations: Sequence[ResearchObservation], dimension: str,
              known: Sequence[str] = ()) -> Matrix:
        rows = require_forward_only(observations)
        grouped = segment(rows, dimension, known)
        cells = {name: MatrixCell(name, evaluate(items,
                                                 minimum_samples=self.minimum_samples))
                 for name, items in grouped.items()}
        return Matrix(dimension, cells, self.minimum_samples)

    def regime(self, observations: Sequence[ResearchObservation]) -> Matrix:
        return self.build(observations, "regime", REGIMES)

    def session(self, observations: Sequence[ResearchObservation]) -> Matrix:
        return self.build(observations, "session", SESSIONS)

    def timeframe(self, observations: Sequence[ResearchObservation]) -> Matrix:
        return self.build(observations, "timeframe", TIMEFRAMES)

    def all(self, observations: Sequence[ResearchObservation]) -> dict[str, Any]:
        return {"regime": self.regime(observations).as_dict(),
                "session": self.session(observations).as_dict(),
                "timeframe": self.timeframe(observations).as_dict()}

    # ------------------------------------------------- 18. regime transitions
    def transitions(self, observations: Sequence[ResearchObservation]) -> Matrix:
        """Performance on observations taken while the regime was changing."""
        rows = [row for row in require_forward_only(observations)
                if row.regime_transition is not None]
        grouped: dict[str, list[ResearchObservation]] = {}
        for row in rows:
            grouped.setdefault(row.regime_transition, []).append(row)
        cells = {name: MatrixCell(name, evaluate(items,
                                                 minimum_samples=self.minimum_samples))
                 for name, items in grouped.items()}
        return Matrix("regime_transition", cells, self.minimum_samples)

    def transition_study(self, observations: Sequence[ResearchObservation]) -> dict[str, Any]:
        """Transitions against the steady state, so the comparison is explicit."""
        rows = require_forward_only(observations)
        moving = [row for row in rows if row.regime_transition is not None]
        steady = [row for row in rows if row.regime_transition is None]
        matrix = self.transitions(rows)
        return {
            "transitions": matrix.as_dict(),
            "during_transition": evaluate(
                moving, minimum_samples=self.minimum_samples).as_dict(),
            "steady_state": evaluate(
                steady, minimum_samples=self.minimum_samples).as_dict(),
            "observed_transitions": sorted(matrix.cells),
            "worst_transition": matrix.worst,
            "best_transition": matrix.best,
            "note": ("A transition cell counts observations whose regime differs from "
                     "the previous one; it is not a claim about causation."),
        }


def signal_quality(observations: Sequence[ResearchObservation], *,
                   minimum_samples: int = 30) -> dict[str, Any]:
    """Section 10's 'signal quality': how often a directional call was made and right."""
    rows = list(observations)
    if not rows:
        return {"samples": 0, "directional_rate": None, "prediction_accuracy": None}
    directional = [row for row in rows if row.predicted in {"UP", "DOWN"}]
    judged = [row for row in rows if row.correct is not None]
    return {
        "samples": len(rows),
        "directional": len(directional),
        "directional_rate": len(directional) / len(rows),
        "prediction_accuracy": (sum(1 for row in judged if row.correct) / len(judged)
                                if judged else None),
        "reliable": len(rows) >= minimum_samples,
    }
