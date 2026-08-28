"""The trading day and its risk budget (section 24).

Timezone ambiguity is the failure mode this module exists to prevent. A "daily"
loss limit is meaningless until the day is pinned down, so the boundary is an
explicit configured timezone plus an explicit reset hour, and every state carries
the trading day it belongs to.

The tracker never closes a position and never releases a limit. Once the daily
loss limit is breached the day stays blocked; the next trading day starts a new
budget, which is the only way the block lifts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from config.settings import load_yaml
from execution.demo.limits import (
    MAX_DAILY_LOSS, MAX_TOTAL_DRAWDOWN, MAX_TRADES_PER_DAY, DemoRiskLimits,
)

NO_STARTING_EQUITY = "DAILY_STARTING_EQUITY_UNKNOWN"


@dataclass(frozen=True, slots=True)
class DailyRiskState:
    trading_day: date
    timezone_name: str
    starting_equity: float
    equity: float
    peak_equity: float
    daily_pnl: float
    daily_drawdown: float
    total_drawdown: float
    trade_count: int
    blocked: bool
    reasons: tuple[str, ...] = ()
    day_start: datetime | None = None
    day_end: datetime | None = None
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def daily_loss(self) -> float:
        """Loss as a positive number; 0 on a profitable day."""
        return max(0.0, -self.daily_pnl)

    def as_dict(self) -> dict[str, Any]:
        return {"trading_day": self.trading_day.isoformat(), "timezone": self.timezone_name,
                "starting_equity": self.starting_equity, "equity": self.equity,
                "peak_equity": self.peak_equity, "daily_pnl": round(self.daily_pnl, 6),
                "daily_loss": round(self.daily_loss, 6),
                "daily_drawdown": round(self.daily_drawdown, 6),
                "total_drawdown": round(self.total_drawdown, 6),
                "trade_count": self.trade_count, "blocked": self.blocked,
                "reasons": list(self.reasons), "day_start": self.day_start,
                "day_end": self.day_end, "updated_at": self.updated_at}


class DailyRiskTracker:
    """Tracks the trading-day budget. It reports; the gate chain does the blocking."""

    def __init__(self, *, limits: DemoRiskLimits | None = None, timezone_name: str | None = None,
                 reset_hour: int | None = None, peak_equity: float | None = None):
        config = load_yaml().get("phase_16", {})
        self.limits = limits or DemoRiskLimits.from_config()
        self.timezone_name = str(timezone_name or config.get("timezone", "UTC"))
        self.zone = ZoneInfo(self.timezone_name)
        self.reset_hour = int(reset_hour if reset_hour is not None
                              else config.get("trading_day_reset_hour", 0))
        if not 0 <= self.reset_hour <= 23:
            raise ValueError("the trading-day reset hour must be between 0 and 23")
        self._day: date | None = None
        self._starting_equity: float | None = None
        self._peak_equity: float | None = peak_equity
        self._trade_count = 0
        self._state: DailyRiskState | None = None

    # ------------------------------------------------------------ day boundary
    @staticmethod
    def _aware(moment: datetime) -> datetime:
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)

    def trading_day(self, moment: datetime) -> date:
        """Which configured trading day a UTC instant belongs to.

        With reset_hour = 22 in a UTC configuration, 21:00 UTC is still the
        previous trading day and 22:00 UTC begins the next one.
        """
        local = self._aware(moment).astimezone(self.zone)
        return (local - timedelta(hours=self.reset_hour)).date()

    def day_bounds(self, moment: datetime) -> tuple[datetime, datetime]:
        day = self.trading_day(moment)
        start_local = datetime.combine(day, datetime.min.time(), tzinfo=self.zone) + timedelta(
            hours=self.reset_hour)
        return start_local.astimezone(timezone.utc), (start_local + timedelta(days=1)).astimezone(
            timezone.utc)

    # ----------------------------------------------------------------- updates
    @property
    def state(self) -> DailyRiskState | None:
        return self._state

    @property
    def trade_count(self) -> int:
        return self._trade_count

    def record_trade(self, count: int = 1) -> int:
        """A submitted order counts against the daily trade budget."""
        self._trade_count += int(count)
        return self._trade_count

    def update(self, *, equity: float, moment: datetime | None = None) -> DailyRiskState:
        """Recompute the day state. Crossing a boundary resets the budget."""
        now = self._aware(moment or datetime.now(timezone.utc))
        day = self.trading_day(now)
        value = float(equity)

        if self._day != day:
            self._day = day
            self._starting_equity = value
            self._trade_count = 0
        if self._starting_equity is None:
            self._starting_equity = value
        # Peak equity spans days: total drawdown is not a daily figure.
        self._peak_equity = value if self._peak_equity is None else max(self._peak_equity, value)

        start = float(self._starting_equity)
        daily_pnl = value - start
        daily_drawdown = max(0.0, -daily_pnl / start) if start else 0.0
        peak = float(self._peak_equity)
        total_drawdown = max(0.0, (peak - value) / peak) if peak else 0.0

        reasons: list[str] = []
        if not start:
            reasons.append(NO_STARTING_EQUITY)
        if daily_drawdown >= self.limits.max_daily_loss:
            reasons.append(MAX_DAILY_LOSS)
        if total_drawdown >= self.limits.max_total_drawdown:
            reasons.append(MAX_TOTAL_DRAWDOWN)
        if self._trade_count >= self.limits.max_trades_per_day:
            reasons.append(MAX_TRADES_PER_DAY)

        day_start, day_end = self.day_bounds(now)
        self._state = DailyRiskState(
            day, self.timezone_name, start, value, peak, daily_pnl, daily_drawdown,
            total_drawdown, self._trade_count, bool(reasons), tuple(reasons),
            day_start, day_end, now)
        return self._state

    def restore(self, state: DailyRiskState) -> DailyRiskState:
        """Reload a persisted day so a restart does not hand back a fresh budget."""
        self._day = state.trading_day
        self._starting_equity = state.starting_equity
        self._peak_equity = state.peak_equity
        self._trade_count = int(state.trade_count)
        self._state = state
        return state
