"""Global execution kill switch.

Naming, stated once so the inversion never bites:

* `engaged = True`  -> execution state DISABLED -> NEW_ENTRY_BLOCKED, DCA_BLOCKED
* `engaged = False` -> execution state ENABLED  -> the guard's other checks decide

`EXECUTION_KILL_SWITCH=true` is the default, so the switch ships engaged and
execution ships blocked.

It never releases itself. There is no timeout, no retry counter and no automatic
recovery: releasing requires an explicit `release()` call from an operator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ExecutionState(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


NEW_ENTRY_BLOCKED = "NEW_ENTRY_BLOCKED"
DCA_BLOCKED = "DCA_BLOCKED"


@dataclass(frozen=True, slots=True)
class KillSwitchEvent:
    timestamp: datetime
    state: ExecutionState
    engaged: bool
    reason: str
    actor: str = "system"
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "state": str(self.state), "engaged": self.engaged,
                "reason": self.reason, "actor": self.actor, "details": self.details}


class ExecutionKillSwitch:
    """Separate from the paper engine's GlobalKillSwitch, which governs simulation."""

    def __init__(self, *, engaged: bool = True, reason: str = "DEFAULT_ENGAGED"):
        self._engaged = bool(engaged)
        self._events: list[KillSwitchEvent] = [
            KillSwitchEvent(self._now(), self.state, self._engaged, reason, actor="config"),
        ]

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @property
    def engaged(self) -> bool:
        return self._engaged

    @property
    def state(self) -> ExecutionState:
        return ExecutionState.DISABLED if self._engaged else ExecutionState.ENABLED

    @property
    def events(self) -> tuple[KillSwitchEvent, ...]:
        return tuple(self._events)

    @property
    def last_event(self) -> KillSwitchEvent:
        return self._events[-1]

    def _record(self, reason: str, actor: str, details: dict[str, Any] | None = None) -> KillSwitchEvent:
        event = KillSwitchEvent(self._now(), self.state, self._engaged, reason, actor, details or {})
        self._events.append(event)
        return event

    def engage(self, reason: str = "MANUAL_ENGAGE", *, actor: str = "operator",
               details: dict[str, Any] | None = None) -> KillSwitchEvent:
        """Block execution. Always permitted, including when already engaged."""
        self._engaged = True
        return self._record(reason, actor, details)

    def release(self, reason: str, *, actor: str = "operator",
                details: dict[str, Any] | None = None) -> KillSwitchEvent:
        """Allow execution again. Deliberate and explicit; nothing calls this on its own."""
        if not reason or not str(reason).strip():
            raise ValueError("releasing the kill switch requires a reason")
        self._engaged = False
        return self._record(str(reason), actor, details)

    def permits(self, *, new_entry: bool = True, increases_exposure: bool = False) -> bool:
        """Engaged blocks both a new entry and any exposure-increasing DCA."""
        if not self._engaged:
            return True
        return not (new_entry or increases_exposure)

    def blocking_reasons(self, *, new_entry: bool = True, increases_exposure: bool = False) -> tuple[str, ...]:
        if not self._engaged:
            return ()
        reasons = []
        if new_entry:
            reasons.append(NEW_ENTRY_BLOCKED)
        if increases_exposure:
            reasons.append(DCA_BLOCKED)
        return tuple(reasons) or (NEW_ENTRY_BLOCKED,)

    def status(self) -> dict[str, Any]:
        last = self.last_event
        return {
            "state": str(self.state), "engaged": self._engaged,
            "execution": "EXECUTION_BLOCKED" if self._engaged else "EXECUTION_ENABLED",
            "since": last.timestamp, "reason": last.reason, "actor": last.actor,
            "auto_release": False,
        }
