"""Daily and weekly reviews (sections 19 and 20).

Two reports with different jobs. The daily review is operational — what happened,
what broke, is the system still healthy. The weekly review is research — is the
Champion still the Champion, is the network contributing anything, does DCA earn
its place, and is there an edge.

Both refuse to flatter. Every figure carries its sample size, the edge status is
whatever the windows say it is, and `INSUFFICIENT_DATA` is the expected answer
for a long time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

REVIEW_VERSION = "phase17.review.v1"


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _window(rows: Sequence[Mapping[str, Any]], *, start: datetime,
            end: datetime) -> list[Mapping[str, Any]]:
    inside = []
    for row in rows:
        stamp = row.get("timestamp") or row.get("closed_at") or row.get("resolved_at")
        if stamp is None:
            continue
        stamp = _aware(stamp)
        if start <= stamp < end:
            inside.append(row)
    return inside


@dataclass(frozen=True, slots=True)
class DailyReview:
    """Section 19."""

    trading_day: date
    timezone_name: str
    signals: int
    trades: int
    wins: int
    losses: int
    net_pnl: float
    drawdown: float
    mae: float | None
    mfe: float | None
    spread: float | None
    slippage: float | None
    execution_failures: int
    model_failures: int
    strategy_failures: int
    regimes: dict[str, int] = field(default_factory=dict)
    sessions: dict[str, int] = field(default_factory=dict)
    edge_status: str = "INSUFFICIENT_DATA"
    circuit_breaker: str = "CLOSED"
    kill_switch: str = "DISABLED"
    anomalies: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    version: str = REVIEW_VERSION
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "trading_day": self.trading_day.isoformat(), "timezone": self.timezone_name,
            "signals": self.signals, "trades": self.trades, "wins": self.wins,
            "losses": self.losses, "net_pnl": round(self.net_pnl, 8),
            "drawdown": round(self.drawdown, 8), "mae": self.mae, "mfe": self.mfe,
            "spread": self.spread, "slippage": self.slippage,
            "execution_failures": self.execution_failures,
            "model_failures": self.model_failures,
            "strategy_failures": self.strategy_failures,
            "regimes": dict(self.regimes), "sessions": dict(self.sessions),
            "edge_status": self.edge_status, "circuit_breaker": self.circuit_breaker,
            "kill_switch": self.kill_switch, "anomalies": list(self.anomalies),
            "reasons": list(self.reasons), "version": self.version,
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True, slots=True)
class WeeklyReview:
    """Section 20."""

    week_start: date
    week_end: date
    champion_strategy: str | None
    champion_model: str | None
    champion_performance: dict[str, Any] = field(default_factory=dict)
    strategy_comparison: dict[str, Any] = field(default_factory=dict)
    nn_contribution: dict[str, Any] = field(default_factory=dict)
    indicator_contribution: dict[str, Any] = field(default_factory=dict)
    dca_contribution: dict[str, Any] = field(default_factory=dict)
    session_performance: dict[str, Any] = field(default_factory=dict)
    regime_performance: dict[str, Any] = field(default_factory=dict)
    timeframe_performance: dict[str, Any] = field(default_factory=dict)
    execution_quality: dict[str, Any] = field(default_factory=dict)
    model_drift: dict[str, Any] = field(default_factory=dict)
    edge_status: str = "INSUFFICIENT_DATA"
    reasons: tuple[str, ...] = ()
    version: str = REVIEW_VERSION
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "week_start": self.week_start.isoformat(), "week_end": self.week_end.isoformat(),
            "champion_strategy": self.champion_strategy,
            "champion_model": self.champion_model,
            "champion_performance": dict(self.champion_performance),
            "strategy_comparison": dict(self.strategy_comparison),
            "nn_contribution": dict(self.nn_contribution),
            "indicator_contribution": dict(self.indicator_contribution),
            "dca_contribution": dict(self.dca_contribution),
            "session_performance": dict(self.session_performance),
            "regime_performance": dict(self.regime_performance),
            "timeframe_performance": dict(self.timeframe_performance),
            "execution_quality": dict(self.execution_quality),
            "model_drift": dict(self.model_drift), "edge_status": self.edge_status,
            "reasons": list(self.reasons),
            "note": ("Forward DEMO observation, not a backtest. A week is rarely "
                     "enough evidence to conclude anything."),
            "version": self.version, "generated_at": self.generated_at,
        }


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _counts(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        name = str(row.get(key) or "UNKNOWN").upper()
        counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


class ReviewBuilder:
    """Assembles the two reports from whatever evidence exists."""

    def __init__(self, *, timezone_name: str = "UTC"):
        self.timezone_name = timezone_name

    def daily(self, *, trading_day: date, start: datetime, end: datetime,
              signals: Sequence[Mapping[str, Any]] = (),
              trades: Sequence[Mapping[str, Any]] = (),
              execution_failures: int = 0, model_failures: int = 0,
              strategy_failures: int = 0, edge_status: str = "INSUFFICIENT_DATA",
              circuit_breaker: str = "CLOSED", kill_switch: str = "DISABLED",
              anomalies: Sequence[str] = ()) -> DailyReview:
        day_signals = _window(signals, start=_aware(start), end=_aware(end))
        day_trades = _window(trades, start=_aware(start), end=_aware(end))

        pnls = [value for value in (_number(row.get("net_pnl")) for row in day_trades)
                if value is not None]
        maes = [value for value in (_number(row.get("mae")) for row in day_trades)
                if value is not None]
        mfes = [value for value in (_number(row.get("mfe")) for row in day_trades)
                if value is not None]
        spreads = [value for value in (_number(row.get("spread")) for row in day_trades)
                   if value is not None]
        slips = [abs(value) for value in (_number(row.get("slippage")) for row in day_trades)
                 if value is not None]

        equity = peak = drawdown = 0.0
        for value in pnls:
            equity += value
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)

        reasons: list[str] = []
        if not day_trades:
            reasons.append("NO_TRADES")
        if not day_signals:
            reasons.append("NO_SIGNALS")

        return DailyReview(
            trading_day=trading_day, timezone_name=self.timezone_name,
            signals=len(day_signals), trades=len(day_trades),
            wins=sum(1 for value in pnls if value > 0),
            losses=sum(1 for value in pnls if value < 0),
            net_pnl=sum(pnls), drawdown=drawdown,
            mae=round(min(maes), 8) if maes else None,
            mfe=round(max(mfes), 8) if mfes else None,
            spread=round(sum(spreads) / len(spreads), 8) if spreads else None,
            slippage=round(sum(slips) / len(slips), 8) if slips else None,
            execution_failures=execution_failures, model_failures=model_failures,
            strategy_failures=strategy_failures,
            regimes=_counts(day_signals or day_trades, "regime"),
            sessions=_counts(day_signals or day_trades, "session"),
            edge_status=str(edge_status), circuit_breaker=str(circuit_breaker),
            kill_switch=str(kill_switch), anomalies=tuple(str(item) for item in anomalies),
            reasons=tuple(reasons))

    def weekly(self, *, week_start: date, champion_strategy: str | None = None,
               champion_model: str | None = None,
               champion_performance: Mapping[str, Any] | None = None,
               strategy_comparison: Mapping[str, Any] | None = None,
               nn_contribution: Mapping[str, Any] | None = None,
               indicator_contribution: Mapping[str, Any] | None = None,
               dca_contribution: Mapping[str, Any] | None = None,
               segments: Mapping[str, Any] | None = None,
               execution_quality: Mapping[str, Any] | None = None,
               model_drift: Mapping[str, Any] | None = None,
               edge_status: str = "INSUFFICIENT_DATA") -> WeeklyReview:
        cuts = dict(segments or {})
        reasons: list[str] = []
        if champion_strategy is None:
            reasons.append("NO_CHAMPION_STRATEGY")
        if not champion_performance:
            reasons.append("NO_CHAMPION_PERFORMANCE")
        if str(edge_status).upper() == "INSUFFICIENT_DATA":
            reasons.append("INSUFFICIENT_DATA")

        return WeeklyReview(
            week_start=week_start, week_end=week_start + timedelta(days=6),
            champion_strategy=champion_strategy, champion_model=champion_model,
            champion_performance=dict(champion_performance or {}),
            strategy_comparison=dict(strategy_comparison or {}),
            nn_contribution=dict(nn_contribution or {}),
            indicator_contribution=dict(indicator_contribution or {}),
            dca_contribution=dict(dca_contribution or {}),
            session_performance=dict(cuts.get("session") or {}),
            regime_performance=dict(cuts.get("regime") or {}),
            timeframe_performance=dict(cuts.get("timeframe") or {}),
            execution_quality=dict(execution_quality or {}),
            model_drift=dict(model_drift or {}), edge_status=str(edge_status),
            reasons=tuple(reasons))
