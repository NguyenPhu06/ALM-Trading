"""The circuit breaker and its recovery (sections 22 and 23).

The Phase 16 emergency controller engages the kill switch. The breaker adds the
thing the kill switch alone cannot give: a state that **survives an operator
releasing the switch**. Without it, recovery would be one button press, and
section 23 asks for four specific things first.

    OPEN  -> health check + risk check + account validation + human approval
          -> CLOSED

`DEMO_AUTOMATED` must not restart on its own, so the breaker never closes itself:
there is no timeout, no retry counter and no automatic reset anywhere in this
module. Like the kill switch, tripping it blocks NEW orders and leaves open
positions alone.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Sequence

from config.settings import load_yaml

logger = logging.getLogger(__name__)

CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
POSITIONS_UNTOUCHED = "OPEN_POSITIONS_NOT_CLOSED"


class BreakerState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"


class BreakerTrigger(StrEnum):
    """Section 22, in full."""

    DAILY_LOSS_EXCEEDED = "DAILY_LOSS_EXCEEDED"
    DRAWDOWN_EXCEEDED = "DRAWDOWN_EXCEEDED"
    RECONCILIATION_FAILURE = "RECONCILIATION_FAILURE"
    REPEATED_EXECUTION_FAILURES = "REPEATED_EXECUTION_FAILURES"
    STALE_MARKET_DATA = "STALE_MARKET_DATA"
    MODEL_FAILURE = "MODEL_FAILURE"
    RISK_ENGINE_FAILURE = "RISK_ENGINE_FAILURE"
    UNEXPECTED_ACCOUNT = "UNEXPECTED_ACCOUNT"
    UNEXPECTED_BROKER = "UNEXPECTED_BROKER"
    UNEXPECTED_SYMBOL = "UNEXPECTED_SYMBOL"
    ABNORMAL_SPREAD = "ABNORMAL_SPREAD"


# Section 23. All four are required; none of them is inferred.
RECOVERY_CHECKS = ("health_check", "risk_check", "account_validation", "human_approval")


@dataclass(frozen=True, slots=True)
class BreakerSignals:
    """What was observed. Unknown stays None and trips nothing."""

    daily_drawdown: float | None = None
    total_drawdown: float | None = None
    reconciliation_failures: int = 0
    execution_failures: int = 0
    data_age_seconds: float | None = None
    model_failed: bool = False
    risk_engine_failed: bool = False
    account_type: str | None = None
    expected_account_type: str = "DEMO"
    broker: str | None = None
    expected_broker: str | None = None
    symbol: str | None = None
    allowed_symbols: tuple[str, ...] = ()
    spread: float | None = None


@dataclass(frozen=True, slots=True)
class RecoveryChecklist:
    """Section 23. Every item explicit, and the approver named."""

    health_check: bool = False
    risk_check: bool = False
    account_validation: bool = False
    approved_by: str | None = None
    reason: str | None = None

    @property
    def human_approval(self) -> bool:
        return bool(str(self.approved_by or "").strip() and str(self.reason or "").strip())

    @property
    def missing(self) -> tuple[str, ...]:
        return tuple(name for name in RECOVERY_CHECKS if not getattr(self, name))

    @property
    def complete(self) -> bool:
        return not self.missing

    def as_dict(self) -> dict[str, Any]:
        return {"health_check": self.health_check, "risk_check": self.risk_check,
                "account_validation": self.account_validation,
                "human_approval": self.human_approval, "approved_by": self.approved_by,
                "reason": self.reason, "complete": self.complete,
                "missing": list(self.missing)}


@dataclass(frozen=True, slots=True)
class BreakerEvent:
    timestamp: datetime
    state: BreakerState
    triggers: tuple[BreakerTrigger, ...] = ()
    reasons: tuple[str, ...] = ()
    actor: str = "system"
    checklist: RecoveryChecklist | None = None
    positions_closed: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"timestamp": self.timestamp, "state": str(self.state),
                "triggers": [str(trigger) for trigger in self.triggers],
                "reasons": list(self.reasons), "actor": self.actor,
                "checklist": self.checklist.as_dict() if self.checklist else None,
                "positions_closed": False, "positions": POSITIONS_UNTOUCHED,
                "details": dict(self.details)}


class RecoveryRefused(RuntimeError):
    """Raised when a reset is attempted without the full checklist."""

    def __init__(self, missing: Sequence[str]):
        self.missing = tuple(missing)
        super().__init__("recovery requires: " + ", ".join(self.missing))


class CircuitBreaker:
    """Trips on the section 22 conditions and refuses to close itself."""

    def __init__(self, settings: Any = None, *, kill_switch: Any = None, alerts: Any = None,
                 repository: Any = None, limits: Any = None,
                 max_execution_failures: int | None = None,
                 data_stale_seconds: float | None = None,
                 abnormal_spread_ratio: float | None = None):
        from execution.demo.limits import DemoRiskLimits

        config = load_yaml().get("phase_17", {}).get("circuit_breaker", {})
        self.settings = settings
        self.kill_switch = kill_switch
        self.alerts = alerts
        self.repository = repository
        self.limits = limits or DemoRiskLimits.from_config()
        self.max_execution_failures = int(
            max_execution_failures if max_execution_failures is not None
            else config.get("max_execution_failures", 3))
        self.data_stale_seconds = float(
            data_stale_seconds if data_stale_seconds is not None
            else config.get("data_stale_seconds", 180))
        # A spread this many times the configured maximum is abnormal, not merely wide.
        self.abnormal_spread_ratio = float(
            abnormal_spread_ratio if abnormal_spread_ratio is not None
            else config.get("abnormal_spread_ratio", 2.0))
        self._state = BreakerState.CLOSED
        self._events: list[BreakerEvent] = []
        self._triggers: tuple[BreakerTrigger, ...] = ()

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> BreakerState:
        return self._state

    @property
    def open(self) -> bool:
        return self._state is BreakerState.OPEN

    @property
    def triggers(self) -> tuple[BreakerTrigger, ...]:
        return self._triggers

    @property
    def events(self) -> tuple[BreakerEvent, ...]:
        return tuple(self._events)

    def blocking_reasons(self) -> tuple[str, ...]:
        if not self.open:
            return ()
        return (CIRCUIT_BREAKER_OPEN, *(str(trigger) for trigger in self._triggers))

    def permits(self) -> bool:
        return not self.open

    # ----------------------------------------------------------------- evaluate
    def evaluate(self, signals: BreakerSignals) -> tuple[BreakerTrigger, ...]:
        """Which section 22 conditions fired. Evaluating never trips the breaker."""
        triggers: list[BreakerTrigger] = []
        if (signals.daily_drawdown is not None
                and signals.daily_drawdown >= self.limits.max_daily_loss):
            triggers.append(BreakerTrigger.DAILY_LOSS_EXCEEDED)
        if (signals.total_drawdown is not None
                and signals.total_drawdown >= self.limits.max_total_drawdown):
            triggers.append(BreakerTrigger.DRAWDOWN_EXCEEDED)
        if signals.reconciliation_failures > 0:
            triggers.append(BreakerTrigger.RECONCILIATION_FAILURE)
        if signals.execution_failures >= self.max_execution_failures:
            triggers.append(BreakerTrigger.REPEATED_EXECUTION_FAILURES)
        if (signals.data_age_seconds is not None
                and signals.data_age_seconds > self.data_stale_seconds):
            triggers.append(BreakerTrigger.STALE_MARKET_DATA)
        if signals.model_failed:
            triggers.append(BreakerTrigger.MODEL_FAILURE)
        if signals.risk_engine_failed:
            triggers.append(BreakerTrigger.RISK_ENGINE_FAILURE)
        if signals.account_type is not None and str(signals.account_type).upper() not in {
                str(signals.expected_account_type).upper(), "CONTEST"}:
            triggers.append(BreakerTrigger.UNEXPECTED_ACCOUNT)
        if (signals.expected_broker and signals.broker
                and str(signals.broker).strip().lower()
                != str(signals.expected_broker).strip().lower()):
            triggers.append(BreakerTrigger.UNEXPECTED_BROKER)
        if signals.allowed_symbols and signals.symbol and str(signals.symbol).upper() not in {
                str(name).upper() for name in signals.allowed_symbols}:
            triggers.append(BreakerTrigger.UNEXPECTED_SYMBOL)
        if (signals.spread is not None
                and signals.spread > self.limits.max_spread * self.abnormal_spread_ratio):
            triggers.append(BreakerTrigger.ABNORMAL_SPREAD)
        return tuple(dict.fromkeys(triggers))

    # --------------------------------------------------------------------- trip
    def trip(self, triggers: Sequence[BreakerTrigger], *, actor: str = "circuit_breaker",
             details: dict[str, Any] | None = None) -> BreakerEvent:
        """Open the breaker and engage the kill switch. Positions are untouched."""
        collected = tuple(BreakerTrigger(trigger) for trigger in triggers)
        self._state = BreakerState.OPEN
        self._triggers = collected
        reasons = tuple(str(trigger) for trigger in collected)
        if self.kill_switch is not None and not self.kill_switch.engaged:
            self.kill_switch.engage(", ".join(reasons) or CIRCUIT_BREAKER_OPEN, actor=actor,
                                    details=dict(details or {}))
        event = BreakerEvent(_utcnow(), BreakerState.OPEN, collected, reasons, actor,
                             details=dict(details or {}))
        return self._record(event, "circuit_breaker_tripped")

    def check(self, signals: BreakerSignals, *, actor: str = "circuit_breaker") -> BreakerEvent | None:
        """Evaluate and trip if anything fired. Returns None when nothing did."""
        if self.settings is not None and not getattr(
                self.settings, "circuit_breaker_enabled", True):
            return None
        triggers = self.evaluate(signals)
        if not triggers:
            return None
        return self.trip(triggers, actor=actor)

    # ------------------------------------------------------------------ recover
    def reset(self, checklist: RecoveryChecklist, *, actor: str | None = None) -> BreakerEvent:
        """Close the breaker. Refuses unless all four section 23 items are satisfied.

        Nothing calls this on its own. There is no timeout and no retry counter,
        so DEMO_AUTOMATED cannot resume by waiting.
        """
        if not checklist.complete:
            raise RecoveryRefused(checklist.missing)
        self._state = BreakerState.CLOSED
        self._triggers = ()
        event = BreakerEvent(_utcnow(), BreakerState.CLOSED, (), ("RECOVERED",),
                             actor or str(checklist.approved_by), checklist)
        return self._record(event, "circuit_breaker_recovered")

    def status(self) -> dict[str, Any]:
        last = self._events[-1] if self._events else None
        return {
            "state": str(self._state), "open": self.open,
            "triggers": [str(trigger) for trigger in self._triggers],
            "blocking_reasons": list(self.blocking_reasons()),
            "since": last.timestamp if last else None,
            "actor": last.actor if last else None,
            "auto_reset": False, "positions_closed": False,
            "recovery_requires": list(RECOVERY_CHECKS),
            "events": [event.as_dict() for event in self._events[-20:]],
        }

    # ----------------------------------------------------------------- plumbing
    def _record(self, event: BreakerEvent, alert: str) -> BreakerEvent:
        self._events.append(event)
        if self.repository is not None and hasattr(self.repository, "save_breaker_event"):
            try:
                self.repository.save_breaker_event(event)
            except Exception:
                logger.exception("failed to persist circuit breaker event")
        if self.alerts is not None:
            handler = getattr(self.alerts, alert, None)
            if handler is not None:
                try:
                    handler(event=event)
                except Exception:
                    logger.exception("circuit breaker alert %s failed", alert)
        logger.warning("circuit breaker %s: %s", event.state, ", ".join(event.reasons))
        return event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
