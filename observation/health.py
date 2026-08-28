"""System-wide health across every Phase 12 component.

Four states per component, ordered by severity so the overall verdict is the
worst one present. UNKNOWN is deliberately worse than DEGRADED: a component we
cannot see is more dangerous than one we know is impaired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable

COMPONENTS = ("api", "database", "mt5", "market_data", "data_quality", "strategy",
              "nn", "risk", "execution", "dashboard", "monitoring")


class ComponentHealth(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


SEVERITY = {
    ComponentHealth.HEALTHY: 0,
    ComponentHealth.DEGRADED: 1,
    ComponentHealth.UNKNOWN: 2,
    ComponentHealth.FAILED: 3,
}


def worst(states: Iterable[ComponentHealth | str]) -> ComponentHealth:
    collected = [ComponentHealth(state) for state in states]
    if not collected:
        return ComponentHealth.UNKNOWN
    return max(collected, key=lambda state: SEVERITY[state])


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    name: str
    state: ComponentHealth
    detail: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "state": str(self.state), "detail": self.detail, **self.details}


@dataclass(frozen=True, slots=True)
class SystemHealth:
    state: ComponentHealth
    components: dict[str, ComponentStatus]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": str(self.state), "timestamp": self.timestamp,
            "last_error": self.last_error,
            **{name: status.as_dict() for name, status in self.components.items()},
        }

    def summary(self) -> dict[str, str]:
        return {name: str(status.state) for name, status in self.components.items()}


class SystemHealthMonitor:
    """Assembles component states. Anything not reported stays UNKNOWN."""

    def __init__(self, *, components: tuple[str, ...] = COMPONENTS):
        self.components = components

    @staticmethod
    def _state(value: Any) -> ComponentHealth:
        if isinstance(value, ComponentHealth):
            return value
        if value is None:
            return ComponentHealth.UNKNOWN
        if isinstance(value, bool):
            return ComponentHealth.HEALTHY if value else ComponentHealth.FAILED
        text = str(value).strip().upper()
        # Map the vocabularies the other subsystems already use.
        mapping = {
            "ONLINE": ComponentHealth.HEALTHY, "HEALTHY": ComponentHealth.HEALTHY,
            "VALID": ComponentHealth.HEALTHY, "PASS": ComponentHealth.HEALTHY,
            "DEGRADED": ComponentHealth.DEGRADED, "WARNING": ComponentHealth.DEGRADED,
            "WARN": ComponentHealth.DEGRADED, "STALE": ComponentHealth.DEGRADED,
            "PARTIAL": ComponentHealth.DEGRADED,
            "OFFLINE": ComponentHealth.FAILED, "ERROR": ComponentHealth.FAILED,
            "FAILED": ComponentHealth.FAILED, "FAIL": ComponentHealth.FAILED,
            "INVALID": ComponentHealth.FAILED,
            "UNAVAILABLE": ComponentHealth.UNKNOWN, "UNKNOWN": ComponentHealth.UNKNOWN,
        }
        return mapping.get(text, ComponentHealth.UNKNOWN)

    def build(self, reported: dict[str, Any] | None = None, *,
              details: dict[str, dict[str, Any]] | None = None,
              last_error: str | None = None,
              now: datetime | None = None) -> SystemHealth:
        reported = reported or {}
        details = details or {}
        statuses: dict[str, ComponentStatus] = {}
        for name in self.components:
            raw = reported.get(name)
            state = self._state(raw)
            detail = None if state is ComponentHealth.HEALTHY else (
                str(raw) if raw is not None else "NOT_REPORTED")
            statuses[name] = ComponentStatus(name, state, detail, details.get(name, {}))
        overall = worst(status.state for status in statuses.values())
        return SystemHealth(overall, statuses, now or datetime.now(timezone.utc), last_error)
