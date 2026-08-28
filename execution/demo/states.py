"""Execution states (section 14) and the transitions between them.

    PROPOSED -> APPROVED -> SUBMITTED -> ACCEPTED -> PARTIALLY_FILLED/FILLED
                                                  -> RECONCILED

BLOCKED, REJECTED, CANCELLED and ERROR are terminal. A blocked order is never
"retried into" an approved one: the next attempt is a new request with its own
id, so the audit trail keeps both.

The lifecycle is append-only. Every transition records who caused it and why,
which is what makes section 28 answerable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class DemoExecutionState(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ERROR = "ERROR"
    RECONCILED = "RECONCILED"


TERMINAL_STATES = frozenset({
    DemoExecutionState.BLOCKED, DemoExecutionState.REJECTED,
    DemoExecutionState.CANCELLED, DemoExecutionState.ERROR,
    DemoExecutionState.RECONCILED,
})

ALLOWED_TRANSITIONS: dict[DemoExecutionState, frozenset[DemoExecutionState]] = {
    DemoExecutionState.PROPOSED: frozenset({
        DemoExecutionState.APPROVED, DemoExecutionState.BLOCKED,
        DemoExecutionState.CANCELLED, DemoExecutionState.ERROR}),
    DemoExecutionState.APPROVED: frozenset({
        DemoExecutionState.SUBMITTED, DemoExecutionState.BLOCKED,
        DemoExecutionState.CANCELLED, DemoExecutionState.ERROR}),
    DemoExecutionState.SUBMITTED: frozenset({
        DemoExecutionState.ACCEPTED, DemoExecutionState.PARTIALLY_FILLED,
        DemoExecutionState.FILLED, DemoExecutionState.REJECTED,
        DemoExecutionState.CANCELLED, DemoExecutionState.ERROR}),
    DemoExecutionState.ACCEPTED: frozenset({
        DemoExecutionState.PARTIALLY_FILLED, DemoExecutionState.FILLED,
        DemoExecutionState.REJECTED, DemoExecutionState.CANCELLED,
        DemoExecutionState.ERROR}),
    DemoExecutionState.PARTIALLY_FILLED: frozenset({
        DemoExecutionState.FILLED, DemoExecutionState.RECONCILED,
        DemoExecutionState.ERROR}),
    DemoExecutionState.FILLED: frozenset({
        DemoExecutionState.RECONCILED, DemoExecutionState.ERROR}),
    DemoExecutionState.BLOCKED: frozenset(),
    DemoExecutionState.REJECTED: frozenset(),
    DemoExecutionState.CANCELLED: frozenset(),
    DemoExecutionState.ERROR: frozenset(),
    DemoExecutionState.RECONCILED: frozenset(),
}


class ExecutionStateError(RuntimeError):
    """Raised when a caller tries to skip, repeat or reverse a state."""


@dataclass(frozen=True, slots=True)
class StateTransition:
    request_id: str
    state: DemoExecutionState
    previous: DemoExecutionState | None
    timestamp: datetime
    actor: str = "system"
    reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "state": str(self.state),
                "previous": str(self.previous) if self.previous else None,
                "timestamp": self.timestamp, "actor": self.actor,
                "reasons": list(self.reasons), "details": dict(self.details)}


class ExecutionLifecycle:
    """One order, one lifecycle. Append-only, and it refuses illegal transitions."""

    def __init__(self, request_id: str, *, state: DemoExecutionState = DemoExecutionState.PROPOSED,
                 actor: str = "system", reasons: tuple[str, ...] = ()):
        self.request_id = str(request_id)
        self._state = DemoExecutionState(state)
        self._history: list[StateTransition] = [
            StateTransition(self.request_id, self._state, None, _utcnow(), actor, tuple(reasons))]

    @property
    def state(self) -> DemoExecutionState:
        return self._state

    @property
    def terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    @property
    def history(self) -> tuple[StateTransition, ...]:
        return tuple(self._history)

    def can_advance(self, target: DemoExecutionState) -> bool:
        return DemoExecutionState(target) in ALLOWED_TRANSITIONS.get(self._state, frozenset())

    def advance(self, target: DemoExecutionState, *, actor: str = "system",
                reasons: Any = (), **details: Any) -> StateTransition:
        state = DemoExecutionState(target)
        if not self.can_advance(state):
            raise ExecutionStateError(f"{self._state} -> {state} is not an allowed transition")
        previous, self._state = self._state, state
        transition = StateTransition(self.request_id, state, previous, _utcnow(), actor,
                                     tuple(str(reason) for reason in (reasons or ())), details)
        self._history.append(transition)
        return transition

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "state": str(self._state),
                "terminal": self.terminal,
                "history": [transition.as_dict() for transition in self._history]}


def state_for_result(result: Any) -> DemoExecutionState:
    """Map a Phase 11 `OrderResult` status onto the Phase 16 state vocabulary."""
    status = str(getattr(result, "status", "") or "").upper()
    return {
        "FILLED": DemoExecutionState.FILLED,
        "PARTIAL": DemoExecutionState.PARTIALLY_FILLED,
        "SUBMITTED": DemoExecutionState.ACCEPTED,
        "REJECTED": DemoExecutionState.REJECTED,
        "BLOCKED": DemoExecutionState.BLOCKED,
        "FAILED": DemoExecutionState.ERROR,
    }.get(status, DemoExecutionState.ERROR)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
