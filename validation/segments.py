"""Regime, session and timeframe performance (sections 10, 11 and 12).

Three cuts of the same population. Each cell carries its own sample size and its
own `reliable` flag, and a cell below the floor is printed but never counted as
evidence — a strategy that is profitable overall can still be losing in BEAR, and
the only way to see that is to refuse to average it away.

Section 12 is a warning as much as a measurement: **do not assume M5 is
superior.** Signals originate on one timeframe and execute on another, so both
are tracked, and the report says where each came from rather than implying the
execution timeframe is the one that produced the edge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import fmean
from typing import Any, Mapping, Sequence

from config.settings import load_yaml

REGIMES = ("STRONG_BULL", "BULL", "RANGE", "BEAR", "STRONG_BEAR")
SESSIONS = ("ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP")
TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")

UNKNOWN = "UNKNOWN"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


@dataclass(frozen=True, slots=True)
class SegmentPerformance:
    key: str
    samples: int
    wins: int
    losses: int
    win_rate: float | None
    expectancy: float | None
    net_pnl: float
    drawdown: float
    mae: float | None
    mfe: float | None
    spread: float | None = None
    slippage: float | None = None
    reliable: bool = False
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "samples": self.samples, "wins": self.wins,
                "losses": self.losses, "win_rate": self.win_rate,
                "expectancy": self.expectancy, "net_pnl": round(self.net_pnl, 8),
                "drawdown": round(self.drawdown, 8), "mae": self.mae, "mfe": self.mfe,
                "spread": self.spread, "slippage": self.slippage,
                "reliable": self.reliable, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class SegmentReport:
    dimension: str
    cells: dict[str, SegmentPerformance]
    reliable_cells: tuple[str, ...] = ()
    best: str | None = None
    worst: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension,
                "cells": {name: cell.as_dict() for name, cell in self.cells.items()},
                "reliable_cells": list(self.reliable_cells),
                # best/worst are named only among cells that cleared the floor.
                "best": self.best, "worst": self.worst,
                "note": "A cell below its sample floor is reported but is not evidence.",
                "timestamp": self.timestamp}


def _evaluate(key: str, rows: Sequence[Mapping[str, Any]], *,
              minimum_samples: int) -> SegmentPerformance:
    pnls = [value for value in (_number(row.get("net_pnl")) for row in rows)
            if value is not None]
    maes = [value for value in (_number(row.get("mae")) for row in rows) if value is not None]
    mfes = [value for value in (_number(row.get("mfe")) for row in rows) if value is not None]
    spreads = [value for value in (_number(row.get("spread")) for row in rows)
               if value is not None]
    slips = [abs(value) for value in (_number(row.get("slippage")) for row in rows)
             if value is not None]

    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    equity = peak = drawdown = 0.0
    for value in pnls:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)

    reliable = len(pnls) >= minimum_samples
    return SegmentPerformance(
        key=key, samples=len(pnls), wins=len(wins), losses=len(losses),
        win_rate=round(len(wins) / len(pnls), 4) if pnls else None,
        expectancy=round(fmean(pnls), 8) if pnls else None,
        net_pnl=sum(pnls), drawdown=drawdown,
        mae=round(fmean(maes), 8) if maes else None,
        mfe=round(fmean(mfes), 8) if mfes else None,
        spread=round(fmean(spreads), 8) if spreads else None,
        slippage=round(fmean(slips), 8) if slips else None,
        reliable=reliable,
        reasons=() if reliable else ("INSUFFICIENT_SAMPLES",))


def _report(dimension: str, rows: Sequence[Mapping[str, Any]], field_name: str,
            known: Sequence[str], minimum_samples: int) -> SegmentReport:
    grouped: dict[str, list[Mapping[str, Any]]] = {name: [] for name in known}
    for row in rows:
        key = str(row.get(field_name) or UNKNOWN).upper()
        grouped.setdefault(key, []).append(row)
    cells = {name: _evaluate(name, values, minimum_samples=minimum_samples)
             for name, values in grouped.items()}
    reliable = tuple(name for name, cell in cells.items() if cell.reliable)
    ranked = sorted((cells[name] for name in reliable),
                    key=lambda cell: cell.expectancy if cell.expectancy is not None else 0.0)
    return SegmentReport(dimension, cells, reliable,
                         best=ranked[-1].key if ranked else None,
                         worst=ranked[0].key if ranked else None)


class SegmentAnalyzer:
    """Cuts a population of resolved trades three ways.

    Each row is a mapping with at least `net_pnl`, plus whichever of `regime`,
    `session`, `timeframe` and `signal_timeframe` is known. Unknown values fall
    into an UNKNOWN cell rather than being dropped, so a systematically
    unlabelled population is visible instead of invisible.
    """

    def __init__(self, *, minimum_regime_samples: int | None = None,
                 minimum_session_samples: int | None = None,
                 minimum_timeframe_samples: int | None = None):
        config = load_yaml().get("phase_17", {}).get("minimums", {})
        self.minimum_regime_samples = int(
            minimum_regime_samples if minimum_regime_samples is not None
            else config.get("minimum_regime_samples", 30))
        self.minimum_session_samples = int(
            minimum_session_samples if minimum_session_samples is not None
            else config.get("minimum_session_samples", 30))
        self.minimum_timeframe_samples = int(
            minimum_timeframe_samples if minimum_timeframe_samples is not None
            else config.get("minimum_timeframe_samples", 30))

    def by_regime(self, rows: Sequence[Mapping[str, Any]]) -> SegmentReport:
        return _report("regime", rows, "regime", REGIMES, self.minimum_regime_samples)

    def by_session(self, rows: Sequence[Mapping[str, Any]]) -> SegmentReport:
        return _report("session", rows, "session", SESSIONS, self.minimum_session_samples)

    def by_timeframe(self, rows: Sequence[Mapping[str, Any]]) -> SegmentReport:
        """Where execution happened."""
        return _report("timeframe", rows, "timeframe", TIMEFRAMES,
                       self.minimum_timeframe_samples)

    def by_signal_timeframe(self, rows: Sequence[Mapping[str, Any]]) -> SegmentReport:
        """Where the signal originated, which is not necessarily where it executed."""
        return _report("signal_timeframe", rows, "signal_timeframe", TIMEFRAMES,
                       self.minimum_timeframe_samples)

    def all(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        execution = self.by_timeframe(rows)
        origin = self.by_signal_timeframe(rows)
        return {
            "regime": self.by_regime(rows).as_dict(),
            "session": self.by_session(rows).as_dict(),
            "timeframe": execution.as_dict(),
            "signal_timeframe": origin.as_dict(),
            "timeframe_note": (
                "Signals originate on one timeframe and execute on another. Neither "
                "table implies M5 is superior; both are reported so the question can "
                "be asked rather than assumed."),
        }
