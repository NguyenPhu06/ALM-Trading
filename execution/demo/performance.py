"""DEMO performance (section 31).

Trading metrics and execution metrics are reported side by side on purpose. A
strategy with a positive expectancy and a 40% order rejection rate is not a
working strategy, and a win rate that ignores commission and swap is not a win
rate.

Sample size is reported with every figure and `reliable` is False until there is
enough of it. A handful of DEMO trades is an anecdote; the honest label for it is
INSUFFICIENT_SAMPLES, not a number with three decimal places.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import fmean
from typing import Any, Sequence

MINIMUM_SAMPLES = 30


@dataclass(frozen=True, slots=True)
class DemoPerformance:
    samples: int
    wins: int
    losses: int
    win_rate: float | None
    expectancy: float | None
    net_pnl: float
    gross_pnl: float
    profit_factor: float | None
    max_drawdown: float
    average_mae: float | None
    average_mfe: float | None
    average_slippage: float | None
    total_commission: float
    total_swap: float
    orders_submitted: int = 0
    orders_rejected: int = 0
    rejection_rate: float | None = None
    reconciliation_errors: int = 0
    by_strategy: dict[str, Any] = field(default_factory=dict)
    by_model: dict[str, Any] = field(default_factory=dict)
    reliable: bool = False
    reasons: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples, "wins": self.wins, "losses": self.losses,
            "win_rate": self.win_rate, "expectancy": self.expectancy,
            "net_pnl": round(self.net_pnl, 6), "gross_pnl": round(self.gross_pnl, 6),
            "profit_factor": self.profit_factor, "max_drawdown": round(self.max_drawdown, 6),
            "average_mae": self.average_mae, "average_mfe": self.average_mfe,
            "average_slippage": self.average_slippage,
            "total_commission": round(self.total_commission, 6),
            "total_swap": round(self.total_swap, 6),
            "orders_submitted": self.orders_submitted, "orders_rejected": self.orders_rejected,
            "rejection_rate": self.rejection_rate,
            "reconciliation_errors": self.reconciliation_errors,
            "by_strategy": dict(self.by_strategy), "by_model": dict(self.by_model),
            "reliable": self.reliable, "reasons": list(self.reasons),
            "timestamp": self.timestamp,
        }


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _group(rows: Sequence[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = {}
    for row in rows:
        name = row.get(key)
        pnl = _number(row.get("pnl"))
        if not name or pnl is None:
            continue
        grouped.setdefault(str(name), []).append(pnl)
    return {name: {"samples": len(values), "net_pnl": round(sum(values), 6),
                   "win_rate": round(sum(value > 0 for value in values) / len(values), 4),
                   "reliable": len(values) >= MINIMUM_SAMPLES}
            for name, values in grouped.items()}


def calculate_demo_performance(entries: Sequence[Any], *, orders_submitted: int = 0,
                               orders_rejected: int = 0, reconciliation_errors: int = 0,
                               minimum_samples: int = MINIMUM_SAMPLES) -> DemoPerformance:
    """Aggregate closed journal entries. Open trades are excluded, never counted as flat."""
    rows = [entry.as_dict() if hasattr(entry, "as_dict") else dict(entry) for entry in entries]
    closed = [row for row in rows if row.get("closed") and _number(row.get("pnl")) is not None]
    total = orders_submitted + orders_rejected
    rejection_rate = round(orders_rejected / total, 4) if total else None

    if not closed:
        return DemoPerformance(0, 0, 0, None, None, 0.0, 0.0, None, 0.0, None, None, None,
                               0.0, 0.0, orders_submitted, orders_rejected, rejection_rate,
                               reconciliation_errors, reliable=False,
                               reasons=("NO_CLOSED_DEMO_TRADES",))

    pnls = [float(_number(row.get("pnl"))) for row in closed]
    gross = [value for value in (_number(row.get("gross_pnl")) for row in closed) if value is not None]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    maes = [value for value in (_number(row.get("mae")) for row in closed) if value is not None]
    mfes = [value for value in (_number(row.get("mfe")) for row in closed) if value is not None]
    slips = [abs(value) for value in (_number(row.get("slippage")) for row in closed)
             if value is not None]

    gain, pain = sum(wins), abs(sum(losses))
    equity, peak, drawdown = 0.0, 0.0, 0.0
    for value in pnls:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)

    reasons = () if len(closed) >= minimum_samples else ("INSUFFICIENT_SAMPLES",)
    return DemoPerformance(
        samples=len(closed), wins=len(wins), losses=len(losses),
        win_rate=round(len(wins) / len(closed), 4),
        expectancy=round(fmean(pnls), 8),
        net_pnl=sum(pnls), gross_pnl=sum(gross) if gross else sum(pnls),
        profit_factor=round(gain / pain, 4) if pain else None,
        max_drawdown=drawdown,
        average_mae=round(fmean(maes), 8) if maes else None,
        average_mfe=round(fmean(mfes), 8) if mfes else None,
        average_slippage=round(fmean(slips), 8) if slips else None,
        total_commission=sum(float(row.get("commission") or 0.0) for row in closed),
        total_swap=sum(float(row.get("swap") or 0.0) for row in closed),
        orders_submitted=orders_submitted, orders_rejected=orders_rejected,
        rejection_rate=rejection_rate, reconciliation_errors=reconciliation_errors,
        by_strategy=_group(closed, "strategy_version"), by_model=_group(closed, "model_version"),
        reliable=len(closed) >= minimum_samples, reasons=reasons)
