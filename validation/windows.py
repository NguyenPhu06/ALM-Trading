"""Rolling forward performance windows and minimum samples (sections 15 and 16).

Seven windows — 24h, 3d, 7d, 14d, 30d, 60d, 90d — computed only **where
sufficient data exists**. A window younger than the data it needs reports
`INSUFFICIENT_DATA` rather than a number, because a 90-day figure computed from
four days of trading is not a 90-day figure.

Section 16 is the gate in front of every claim in this package: an edge is never
declared from a tiny sample, and the minimums are configurable rather than
hardcoded so the bar can be raised but not silently lowered in code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from statistics import fmean
from typing import Any, Mapping, Sequence

from config.settings import load_yaml

# Section 15, in order.
WINDOWS: tuple[tuple[str, timedelta], ...] = (
    ("24h", timedelta(hours=24)),
    ("3d", timedelta(days=3)),
    ("7d", timedelta(days=7)),
    ("14d", timedelta(days=14)),
    ("30d", timedelta(days=30)),
    ("60d", timedelta(days=60)),
    ("90d", timedelta(days=90)),
)


class EdgeStatus(StrEnum):
    EDGE_DETECTED = "EDGE_DETECTED"
    UNSTABLE_EDGE = "UNSTABLE_EDGE"
    NO_EDGE = "NO_EDGE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class SampleRequirements:
    """Section 16. Every floor configurable; none of them optional."""

    minimum_signals: int = 100
    minimum_winning_signals: int = 20
    minimum_losing_signals: int = 20
    minimum_regime_samples: int = 30
    minimum_session_samples: int = 30
    minimum_timeframe_samples: int = 30

    @classmethod
    def from_config(cls, overrides: Mapping[str, Any] | None = None) -> "SampleRequirements":
        config = dict(load_yaml().get("phase_17", {}).get("minimums", {}))
        config.update(dict(overrides or {}))
        known = {"minimum_signals", "minimum_winning_signals", "minimum_losing_signals",
                 "minimum_regime_samples", "minimum_session_samples",
                 "minimum_timeframe_samples"}
        return cls(**{name: int(value) for name, value in config.items() if name in known})

    def shortfalls(self, *, signals: int, wins: int, losses: int) -> tuple[str, ...]:
        """Which floors this population misses. Empty means it clears them all."""
        gaps: list[str] = []
        if signals < self.minimum_signals:
            gaps.append("MINIMUM_SIGNALS")
        if wins < self.minimum_winning_signals:
            gaps.append("MINIMUM_WINNING_SIGNALS")
        if losses < self.minimum_losing_signals:
            gaps.append("MINIMUM_LOSING_SIGNALS")
        return tuple(gaps)

    def as_dict(self) -> dict[str, Any]:
        return {"minimum_signals": self.minimum_signals,
                "minimum_winning_signals": self.minimum_winning_signals,
                "minimum_losing_signals": self.minimum_losing_signals,
                "minimum_regime_samples": self.minimum_regime_samples,
                "minimum_session_samples": self.minimum_session_samples,
                "minimum_timeframe_samples": self.minimum_timeframe_samples}


@dataclass(frozen=True, slots=True)
class WindowPerformance:
    window: str
    samples: int
    wins: int
    losses: int
    win_rate: float | None
    expectancy: float | None
    profit_factor: float | None
    net_pnl: float
    drawdown: float
    mae: float | None
    mfe: float | None
    covered: bool
    edge_status: EdgeStatus
    reasons: tuple[str, ...] = ()

    @property
    def reliable(self) -> bool:
        return self.edge_status is not EdgeStatus.INSUFFICIENT_DATA

    def as_dict(self) -> dict[str, Any]:
        return {"window": self.window, "samples": self.samples, "wins": self.wins,
                "losses": self.losses, "win_rate": self.win_rate,
                "expectancy": self.expectancy, "profit_factor": self.profit_factor,
                "net_pnl": round(self.net_pnl, 8), "drawdown": round(self.drawdown, 8),
                "mae": self.mae, "mfe": self.mfe, "covered": self.covered,
                "edge_status": str(self.edge_status), "reliable": self.reliable,
                "reasons": list(self.reasons)}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class RollingWindowEvaluator:
    """Cuts a population into the seven windows and rates each one."""

    def __init__(self, requirements: SampleRequirements | None = None, *,
                 minimum_expectancy: float | None = None):
        config = load_yaml().get("phase_17", {}).get("edge", {})
        self.requirements = requirements or SampleRequirements.from_config()
        # An expectancy this small is indistinguishable from zero after cost.
        self.minimum_expectancy = float(
            minimum_expectancy if minimum_expectancy is not None
            else config.get("minimum_expectancy", 0.0))

    def evaluate(self, rows: Sequence[Mapping[str, Any]], *, window: str,
                 span: timedelta, now: datetime | None = None,
                 earliest: datetime | None = None) -> WindowPerformance:
        moment = _aware(now or datetime.now(timezone.utc))
        cutoff = moment - span
        inside = []
        for row in rows:
            stamp = row.get("timestamp") or row.get("closed_at") or row.get("resolved_at")
            if stamp is None:
                continue
            if _aware(stamp) >= cutoff:
                inside.append(row)

        # "Where sufficient data exists": a 90d window over 4 days of history is
        # not a 90d measurement, whatever the row count says.
        covered = earliest is None or (moment - _aware(earliest)) >= span

        pnls = [value for value in (_number(row.get("net_pnl")) for row in inside)
                if value is not None]
        maes = [value for value in (_number(row.get("mae")) for row in inside)
                if value is not None]
        mfes = [value for value in (_number(row.get("mfe")) for row in inside)
                if value is not None]
        wins = [value for value in pnls if value > 0]
        losses = [value for value in pnls if value < 0]
        gain, pain = sum(wins), abs(sum(losses))

        equity = peak = drawdown = 0.0
        for value in pnls:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)

        expectancy = fmean(pnls) if pnls else None
        shortfalls = self.requirements.shortfalls(
            signals=len(pnls), wins=len(wins), losses=len(losses))
        reasons = list(shortfalls)
        if not covered:
            reasons.append("WINDOW_NOT_COVERED")

        if reasons:
            status = EdgeStatus.INSUFFICIENT_DATA
        elif expectancy is not None and expectancy > self.minimum_expectancy:
            status = EdgeStatus.EDGE_DETECTED
        elif expectancy is not None and expectancy > 0:
            # Positive but inside the noise floor.
            status = EdgeStatus.UNSTABLE_EDGE
            reasons.append("EXPECTANCY_BELOW_MINIMUM")
        else:
            status = EdgeStatus.NO_EDGE

        return WindowPerformance(
            window=window, samples=len(pnls), wins=len(wins), losses=len(losses),
            win_rate=round(len(wins) / len(pnls), 4) if pnls else None,
            expectancy=round(expectancy, 8) if expectancy is not None else None,
            profit_factor=round(gain / pain, 4) if pain else None,
            net_pnl=sum(pnls), drawdown=drawdown,
            mae=round(fmean(maes), 8) if maes else None,
            mfe=round(fmean(mfes), 8) if mfes else None,
            covered=covered, edge_status=status, reasons=tuple(dict.fromkeys(reasons)))

    def all(self, rows: Sequence[Mapping[str, Any]], *, now: datetime | None = None
            ) -> dict[str, Any]:
        moment = _aware(now or datetime.now(timezone.utc))
        stamps = [_aware(row["timestamp"]) for row in rows
                  if row.get("timestamp") is not None]
        earliest = min(stamps) if stamps else None
        windows = {name: self.evaluate(rows, window=name, span=span, now=moment,
                                       earliest=earliest)
                   for name, span in WINDOWS}
        detected = [name for name, result in windows.items()
                    if result.edge_status is EdgeStatus.EDGE_DETECTED]
        return {
            "windows": {name: result.as_dict() for name, result in windows.items()},
            "requirements": self.requirements.as_dict(),
            "earliest": earliest,
            # An edge in one window and not the others is instability, not an edge.
            "edge_status": str(self._overall(windows)),
            "windows_with_edge": detected,
        }

    @staticmethod
    def _overall(windows: Mapping[str, WindowPerformance]) -> EdgeStatus:
        rated = [result for result in windows.values()
                 if result.edge_status is not EdgeStatus.INSUFFICIENT_DATA]
        if not rated:
            return EdgeStatus.INSUFFICIENT_DATA
        detected = [result for result in rated
                    if result.edge_status is EdgeStatus.EDGE_DETECTED]
        if not detected:
            return EdgeStatus.NO_EDGE
        if len(detected) < len(rated):
            return EdgeStatus.UNSTABLE_EDGE
        return EdgeStatus.EDGE_DETECTED
