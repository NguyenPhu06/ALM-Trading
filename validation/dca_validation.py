"""DCA validation (section 14).

DCA is disabled by default and this module does not change that. It measures a
DCA population *if one exists*, level by level, and compares it with NO_DCA.

The decisive rule is in the spec and implemented literally: **reject DCA if the
increased win rate is achieved only through materially increased tail risk.** A
strategy that wins more often and loses far more when it loses has not improved;
it has moved the loss somewhere less visible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from statistics import fmean
from typing import Any, Mapping, Sequence

from config.settings import load_yaml


class DCAVerdict(StrEnum):
    IMPROVES = "IMPROVES"
    NOT_PROVEN = "NOT_PROVEN"
    REJECTED_TAIL_RISK = "REJECTED_TAIL_RISK"
    HARMFUL = "HARMFUL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    DISABLED = "DISABLED"


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _tail(values: Sequence[float], fraction: float = 0.05) -> float | None:
    """Mean of the worst `fraction` of outcomes. The number DCA hides."""
    rows = sorted(values)
    if not rows:
        return None
    count = max(1, int(round(len(rows) * fraction)))
    return round(fmean(rows[:count]), 8)


@dataclass(frozen=True, slots=True)
class DCALevelStats:
    level: int
    entries: int
    average_entry: float | None
    volume: float
    exposure: float
    risk: float
    mae: float | None
    mfe: float | None

    def as_dict(self) -> dict[str, Any]:
        return {"level": self.level, "entries": self.entries,
                "average_entry": self.average_entry, "volume": round(self.volume, 6),
                "exposure": round(self.exposure, 2), "risk": round(self.risk, 2),
                "mae": self.mae, "mfe": self.mfe}


@dataclass(frozen=True, slots=True)
class DCAArm:
    name: str
    samples: int
    win_rate: float | None
    expectancy: float | None
    net_pnl: float
    drawdown: float
    tail_loss: float | None
    worst_loss: float | None
    mae: float | None
    mfe: float | None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "samples": self.samples, "win_rate": self.win_rate,
                "expectancy": self.expectancy, "net_pnl": round(self.net_pnl, 8),
                "drawdown": round(self.drawdown, 8), "tail_loss": self.tail_loss,
                "worst_loss": self.worst_loss, "mae": self.mae, "mfe": self.mfe}


@dataclass(frozen=True, slots=True)
class DCAValidationReport:
    verdict: DCAVerdict
    dca: DCAArm | None
    no_dca: DCAArm | None
    levels: tuple[DCALevelStats, ...] = ()
    aggregate_exposure: float = 0.0
    aggregate_risk: float = 0.0
    win_rate_delta: float | None = None
    expectancy_delta: float | None = None
    tail_delta: float | None = None
    reasons: tuple[str, ...] = ()
    recommended: str = "NO_DCA"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict),
            "dca": self.dca.as_dict() if self.dca else None,
            "no_dca": self.no_dca.as_dict() if self.no_dca else None,
            "levels": [level.as_dict() for level in self.levels],
            "aggregate_exposure": round(self.aggregate_exposure, 2),
            "aggregate_risk": round(self.aggregate_risk, 2),
            "win_rate_delta": self.win_rate_delta,
            "expectancy_delta": self.expectancy_delta, "tail_delta": self.tail_delta,
            "recommended": self.recommended, "reasons": list(self.reasons),
            "note": ("DCA is rejected when a higher win rate is bought with materially "
                     "worse tail risk. NO_DCA is the default recommendation."),
            "timestamp": self.timestamp,
        }


def _arm(name: str, rows: Sequence[Mapping[str, Any]]) -> DCAArm:
    pnls = [value for value in (_number(row.get("net_pnl")) for row in rows)
            if value is not None]
    maes = [value for value in (_number(row.get("mae")) for row in rows) if value is not None]
    mfes = [value for value in (_number(row.get("mfe")) for row in rows) if value is not None]
    wins = [value for value in pnls if value > 0]
    equity = peak = drawdown = 0.0
    for value in pnls:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return DCAArm(
        name=name, samples=len(pnls),
        win_rate=round(len(wins) / len(pnls), 4) if pnls else None,
        expectancy=round(fmean(pnls), 8) if pnls else None,
        net_pnl=sum(pnls), drawdown=drawdown, tail_loss=_tail(pnls),
        worst_loss=round(min(pnls), 8) if pnls else None,
        mae=round(fmean(maes), 8) if maes else None,
        mfe=round(fmean(mfes), 8) if mfes else None)


class DCAValidator:
    """Measures a DCA population level by level and against NO_DCA."""

    def __init__(self, *, minimum_samples: int | None = None,
                 tail_tolerance: float | None = None, settings: Any = None):
        config = load_yaml().get("phase_17", {}).get("dca", {})
        self.minimum_samples = int(
            minimum_samples if minimum_samples is not None
            else config.get("minimum_samples", 30))
        # How much worse the tail may get before a win-rate gain is rejected.
        self.tail_tolerance = float(
            tail_tolerance if tail_tolerance is not None
            else config.get("tail_tolerance", 0.20))
        self.settings = settings

    def levels(self, trades: Sequence[Mapping[str, Any]]) -> tuple[DCALevelStats, ...]:
        """Section 14: every level tracked independently, initial entry included."""
        buckets: dict[int, list[Mapping[str, Any]]] = {}
        for trade in trades:
            for entry in (trade.get("entries") or []):
                level = int(entry.get("level", 0))
                buckets.setdefault(level, []).append(entry)
        stats: list[DCALevelStats] = []
        for level in sorted(buckets):
            rows = buckets[level]
            prices = [value for value in (_number(row.get("price")) for row in rows)
                      if value is not None]
            maes = [value for value in (_number(row.get("mae")) for row in rows)
                    if value is not None]
            mfes = [value for value in (_number(row.get("mfe")) for row in rows)
                    if value is not None]
            stats.append(DCALevelStats(
                level=level, entries=len(rows),
                average_entry=round(fmean(prices), 8) if prices else None,
                volume=sum(_number(row.get("volume")) or 0.0 for row in rows),
                exposure=sum(_number(row.get("exposure")) or 0.0 for row in rows),
                risk=sum(_number(row.get("risk")) or 0.0 for row in rows),
                mae=round(fmean(maes), 8) if maes else None,
                mfe=round(fmean(mfes), 8) if mfes else None))
        return tuple(stats)

    def evaluate(self, dca_trades: Sequence[Mapping[str, Any]],
                 no_dca_trades: Sequence[Mapping[str, Any]], *,
                 enabled: bool | None = None) -> DCAValidationReport:
        if enabled is None and self.settings is not None:
            enabled = bool(getattr(self.settings, "demo_dca_enabled", False))
        levels = self.levels(dca_trades)
        aggregate_exposure = sum(level.exposure for level in levels)
        aggregate_risk = sum(level.risk for level in levels)

        if enabled is False and not dca_trades:
            return DCAValidationReport(
                DCAVerdict.DISABLED, None, None, levels, aggregate_exposure, aggregate_risk,
                reasons=("DCA_DISABLED",))

        dca = _arm("DCA", dca_trades)
        flat = _arm("NO_DCA", no_dca_trades)
        reasons: list[str] = []

        if min(dca.samples, flat.samples) < self.minimum_samples:
            reasons.append("INSUFFICIENT_SAMPLES")
            return DCAValidationReport(
                DCAVerdict.INSUFFICIENT_DATA, dca, flat, levels, aggregate_exposure,
                aggregate_risk, reasons=tuple(reasons))

        win_delta = _delta(dca.win_rate, flat.win_rate)
        expectancy_delta = _delta(dca.expectancy, flat.expectancy)
        # Tail is negative; a more negative DCA tail is a worse one.
        tail_delta = _delta(dca.tail_loss, flat.tail_loss)

        worse_tail = False
        if dca.tail_loss is not None and flat.tail_loss is not None and flat.tail_loss < 0:
            worse_tail = dca.tail_loss < flat.tail_loss * (1.0 + self.tail_tolerance)

        # The tail-risk cases are tested first, and deliberately so. When a DCA
        # arm wins more often AND has a materially worse tail, "HARMFUL" would be
        # true but useless: REJECTED_TAIL_RISK names *why*, which is the named
        # trap in section 14 and the one an operator needs to see.
        if worse_tail and (win_delta or 0.0) > 0:
            reasons.append("WIN_RATE_BOUGHT_WITH_TAIL_RISK")
            if expectancy_delta is not None and expectancy_delta < 0:
                reasons.append("EXPECTANCY_WORSE_THAN_NO_DCA")
            verdict = DCAVerdict.REJECTED_TAIL_RISK
        elif worse_tail:
            reasons.append("TAIL_RISK_MATERIALLY_WORSE")
            verdict = DCAVerdict.REJECTED_TAIL_RISK
        elif expectancy_delta is not None and expectancy_delta < 0:
            reasons.append("EXPECTANCY_WORSE_THAN_NO_DCA")
            verdict = DCAVerdict.HARMFUL
        elif expectancy_delta is not None and expectancy_delta > 0:
            verdict = DCAVerdict.IMPROVES
        else:
            reasons.append("NO_MEASURABLE_IMPROVEMENT")
            verdict = DCAVerdict.NOT_PROVEN

        return DCAValidationReport(
            verdict=verdict, dca=dca, no_dca=flat, levels=levels,
            aggregate_exposure=aggregate_exposure, aggregate_risk=aggregate_risk,
            win_rate_delta=win_delta, expectancy_delta=expectancy_delta,
            tail_delta=tail_delta, reasons=tuple(reasons),
            recommended="DCA" if verdict is DCAVerdict.IMPROVES else "NO_DCA")


def _delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 8)
