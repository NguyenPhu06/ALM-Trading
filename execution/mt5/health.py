"""MT5 connection and data-freshness health.

States are ordered by severity so an overall verdict is the worst component.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from data_quality.validator import timeframe_delta


class HealthState(StrEnum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    STALE = "STALE"
    OFFLINE = "OFFLINE"
    ERROR = "ERROR"


SEVERITY = {
    HealthState.ONLINE: 0, HealthState.DEGRADED: 1, HealthState.STALE: 2,
    HealthState.OFFLINE: 3, HealthState.ERROR: 4,
}


def worst(states: Any) -> HealthState:
    collected = [HealthState(state) for state in states]
    if not collected:
        return HealthState.OFFLINE
    return max(collected, key=lambda state: SEVERITY[state])


@dataclass(frozen=True, slots=True)
class HealthComponent:
    name: str
    state: HealthState
    detail: str | None = None
    age_seconds: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "state": str(self.state), "detail": self.detail,
                "age_seconds": self.age_seconds}


@dataclass(frozen=True, slots=True)
class HealthReport:
    timestamp: datetime
    state: HealthState
    components: tuple[HealthComponent, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "state": str(self.state),
                "components": [component.as_dict() for component in self.components],
                **self.details}


class MT5HealthMonitor:
    """Aggregates terminal, connection, account, tick and candle freshness."""

    def __init__(self, *, tick_stale_seconds: float = 30.0, candle_stale_multiplier: float = 3.0):
        self.tick_stale_seconds = float(tick_stale_seconds)
        self.candle_stale_multiplier = float(candle_stale_multiplier)

    @staticmethod
    def _age(timestamp: datetime | None, now: datetime) -> float | None:
        if timestamp is None:
            return None
        aware = timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)
        return max(0.0, (now - aware).total_seconds())

    def tick_component(self, symbol: str, timestamp: datetime | None, now: datetime) -> HealthComponent:
        age = self._age(timestamp, now)
        if age is None:
            return HealthComponent(f"tick:{symbol}", HealthState.OFFLINE, "NO_TICK")
        state = HealthState.STALE if age > self.tick_stale_seconds else HealthState.ONLINE
        return HealthComponent(f"tick:{symbol}", state, None, round(age, 3))

    def candle_component(self, symbol: str, timeframe: str, timestamp: datetime | None,
                         now: datetime) -> HealthComponent:
        age = self._age(timestamp, now)
        name = f"candle:{symbol}:{timeframe}"
        if age is None:
            return HealthComponent(name, HealthState.OFFLINE, "NO_CANDLE")
        budget = timeframe_delta(timeframe).total_seconds() * self.candle_stale_multiplier
        state = HealthState.STALE if age > budget else HealthState.ONLINE
        return HealthComponent(name, state, None, round(age, 3))

    def check(self, *, terminal_available: bool, connected: bool, account_valid: bool,
              server: str | None = None, database_online: bool | None = None,
              api_online: bool = True, ticks: dict[str, datetime | None] | None = None,
              candles: dict[tuple[str, str], datetime | None] | None = None,
              error: str | None = None, blocked: bool = False,
              now: datetime | None = None) -> HealthReport:
        moment = now or datetime.now(timezone.utc)
        components: list[HealthComponent] = []

        if error:
            components.append(HealthComponent("terminal", HealthState.ERROR, error))
        elif blocked:
            components.append(HealthComponent("terminal", HealthState.OFFLINE, "BLOCKED_BY_SAFETY_LOCK"))
        elif not terminal_available:
            components.append(HealthComponent("terminal", HealthState.OFFLINE, "MT5_TERMINAL_NOT_AVAILABLE"))
        else:
            components.append(HealthComponent("terminal", HealthState.ONLINE))

        components.append(HealthComponent(
            "connection", HealthState.ONLINE if connected else HealthState.OFFLINE,
            None if connected else "MT5_NOT_CONNECTED"))
        components.append(HealthComponent(
            "account", HealthState.ONLINE if account_valid else HealthState.DEGRADED,
            None if account_valid else "ACCOUNT_NOT_VALIDATED"))
        components.append(HealthComponent(
            "server", HealthState.ONLINE if server else HealthState.DEGRADED,
            None if server else "SERVER_UNKNOWN"))
        if database_online is not None:
            components.append(HealthComponent(
                "database", HealthState.ONLINE if database_online else HealthState.OFFLINE))
        components.append(HealthComponent("api", HealthState.ONLINE if api_online else HealthState.OFFLINE))

        for symbol, stamp in (ticks or {}).items():
            components.append(self.tick_component(symbol, stamp, moment))
        for (symbol, timeframe), stamp in (candles or {}).items():
            components.append(self.candle_component(symbol, timeframe, stamp, moment))

        overall = worst(component.state for component in components)
        return HealthReport(moment, overall, tuple(components), {
            "server": server, "connected": connected, "account_valid": account_valid,
            "terminal_available": terminal_available,
        })
