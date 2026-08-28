"""Emergency protection (section 17).

Eleven conditions shut execution down automatically. "Shut down" means one thing
and one thing only: the kill switch is engaged and no NEW order may be sent.

Open positions are deliberately left alone. Closing them automatically would be a
second, larger and less reversible decision taken by the same code that just
discovered it could not trust its own inputs — the connection may be unstable,
the data stale, the account not what it claimed. Section 16 says the same thing
about the kill switch, and this module honours it: liquidation requires an
explicit, separately authorised instruction.

Recovery is never automatic either. Once the switch is engaged, an operator
releases it with a reason, exactly as in Phase 11.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from config.settings import Settings, get_settings, load_yaml
from execution.demo.limits import DemoRiskLimits

logger = logging.getLogger(__name__)


class EmergencyTrigger(StrEnum):
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"
    EXECUTION_ERRORS = "EXECUTION_ERRORS"
    MT5_CONNECTION_UNSTABLE = "MT5_CONNECTION_UNSTABLE"
    DATA_STALE = "DATA_STALE"
    RECONCILIATION_FAILURE = "RECONCILIATION_FAILURE"
    UNEXPECTED_ACCOUNT_TYPE = "UNEXPECTED_ACCOUNT_TYPE"
    UNEXPECTED_BROKER = "UNEXPECTED_BROKER"
    SPREAD_LIMIT = "SPREAD_LIMIT"
    MODEL_FAILURE = "MODEL_FAILURE"
    RISK_ENGINE_FAILURE = "RISK_ENGINE_FAILURE"


# Triggers whose severity is absolute: one occurrence is enough, no counting.
IMMEDIATE = frozenset({
    EmergencyTrigger.UNEXPECTED_ACCOUNT_TYPE, EmergencyTrigger.UNEXPECTED_BROKER,
    EmergencyTrigger.RECONCILIATION_FAILURE, EmergencyTrigger.DAILY_LOSS_LIMIT,
    EmergencyTrigger.DRAWDOWN_LIMIT, EmergencyTrigger.RISK_ENGINE_FAILURE,
})

SHUTDOWN_ACTION = "EXECUTION_SHUTDOWN"
POSITIONS_UNTOUCHED = "OPEN_POSITIONS_NOT_CLOSED"


@dataclass(frozen=True, slots=True)
class EmergencySignals:
    """What the caller observed. Unknown stays None and triggers nothing."""

    daily_drawdown: float | None = None
    total_drawdown: float | None = None
    execution_errors: int = 0
    connection_failures: int = 0
    connected: bool = True
    data_age_seconds: float | None = None
    reconciliation_failures: int = 0
    account_type: str | None = None
    expected_account_type: str = "DEMO"
    broker: str | None = None
    expected_broker: str | None = None
    server: str | None = None
    expected_server: str | None = None
    spread: float | None = None
    model_failed: bool = False
    risk_engine_failed: bool = False


@dataclass(frozen=True, slots=True)
class EmergencyDecision:
    shutdown: bool
    triggers: tuple[EmergencyTrigger, ...] = ()
    reasons: tuple[str, ...] = ()
    action: str | None = None
    positions_closed: bool = False
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {"shutdown": self.shutdown,
                "triggers": [str(trigger) for trigger in self.triggers],
                "reasons": list(self.reasons), "action": self.action,
                "positions_closed": self.positions_closed,
                "positions": POSITIONS_UNTOUCHED, "details": dict(self.details),
                "timestamp": self.timestamp}


class EmergencyController:
    """Evaluates the shutdown conditions and engages the kill switch when they fire."""

    def __init__(self, settings: Settings | None = None, *, kill_switch: Any = None,
                 limits: DemoRiskLimits | None = None, alerts: Any = None,
                 repository: Any = None):
        self.settings = settings or get_settings()
        config = load_yaml().get("phase_16", {}).get("emergency", {})
        self.limits = limits or DemoRiskLimits.from_config()
        self.kill_switch = kill_switch
        self.alerts = alerts
        self.repository = repository
        self.max_execution_errors = int(config.get("max_execution_errors", 3))
        self.max_reconciliation_failures = int(
            config.get("max_consecutive_reconciliation_failures", 1))
        self.connection_failure_threshold = int(config.get("connection_failure_threshold", 3))
        self.data_stale_seconds = float(config.get("data_stale_seconds", 180))

    # ---------------------------------------------------------------- evaluate
    def evaluate(self, signals: EmergencySignals) -> EmergencyDecision:
        triggers: list[EmergencyTrigger] = []
        details: dict[str, Any] = {}

        if signals.daily_drawdown is not None and signals.daily_drawdown >= self.limits.max_daily_loss:
            triggers.append(EmergencyTrigger.DAILY_LOSS_LIMIT)
            details["daily_drawdown"] = signals.daily_drawdown
        if signals.total_drawdown is not None and signals.total_drawdown >= self.limits.max_total_drawdown:
            triggers.append(EmergencyTrigger.DRAWDOWN_LIMIT)
            details["total_drawdown"] = signals.total_drawdown
        if signals.execution_errors >= self.max_execution_errors:
            triggers.append(EmergencyTrigger.EXECUTION_ERRORS)
            details["execution_errors"] = signals.execution_errors
        if not signals.connected or signals.connection_failures >= self.connection_failure_threshold:
            triggers.append(EmergencyTrigger.MT5_CONNECTION_UNSTABLE)
            details["connection_failures"] = signals.connection_failures
        if signals.data_age_seconds is not None and signals.data_age_seconds > self.data_stale_seconds:
            triggers.append(EmergencyTrigger.DATA_STALE)
            details["data_age_seconds"] = signals.data_age_seconds
        if signals.reconciliation_failures >= self.max_reconciliation_failures:
            triggers.append(EmergencyTrigger.RECONCILIATION_FAILURE)
            details["reconciliation_failures"] = signals.reconciliation_failures
        if signals.account_type is not None and str(signals.account_type).upper() not in {
                str(signals.expected_account_type).upper(), "CONTEST"}:
            triggers.append(EmergencyTrigger.UNEXPECTED_ACCOUNT_TYPE)
            details["account_type"] = signals.account_type
        for observed, expected, key in ((signals.broker, signals.expected_broker, "broker"),
                                        (signals.server, signals.expected_server, "server")):
            if expected and observed and str(observed).strip().lower() != str(expected).strip().lower():
                triggers.append(EmergencyTrigger.UNEXPECTED_BROKER)
                details[key] = observed
        if signals.spread is not None and signals.spread > self.limits.max_spread:
            triggers.append(EmergencyTrigger.SPREAD_LIMIT)
            details["spread"] = signals.spread
        if signals.model_failed:
            triggers.append(EmergencyTrigger.MODEL_FAILURE)
        if signals.risk_engine_failed:
            triggers.append(EmergencyTrigger.RISK_ENGINE_FAILURE)

        unique = tuple(dict.fromkeys(triggers))
        return EmergencyDecision(
            bool(unique), unique, tuple(str(trigger) for trigger in unique),
            SHUTDOWN_ACTION if unique else None, False, details)

    # ---------------------------------------------------------------- shutdown
    def shutdown(self, decision: EmergencyDecision, *, actor: str = "emergency") -> EmergencyDecision:
        """Engage the kill switch. Open positions are never closed here."""
        if not decision.shutdown:
            return decision
        reason = ", ".join(decision.reasons) or SHUTDOWN_ACTION
        if self.kill_switch is not None and not self.kill_switch.engaged:
            event = self.kill_switch.engage(reason, actor=actor, details=dict(decision.details))
            if self.repository is not None and hasattr(self.repository, "save_kill_switch_event"):
                try:
                    self.repository.save_kill_switch_event(event)
                except Exception:
                    logger.exception("failed to persist the emergency kill-switch event")
        if self.repository is not None and hasattr(self.repository, "save_emergency_event"):
            try:
                self.repository.save_emergency_event(decision)
            except Exception:
                logger.exception("failed to persist the emergency event")
        self._alert(decision)
        logger.error("emergency shutdown: %s", reason)
        return decision

    def check(self, signals: EmergencySignals, *, actor: str = "emergency") -> EmergencyDecision:
        return self.shutdown(self.evaluate(signals), actor=actor)

    def _alert(self, decision: EmergencyDecision) -> None:
        if self.alerts is None:
            return
        handler = getattr(self.alerts, "emergency_shutdown", None)
        if handler is None:
            return
        try:
            handler(decision=decision)
        except Exception:
            logger.exception("emergency alert failed")
