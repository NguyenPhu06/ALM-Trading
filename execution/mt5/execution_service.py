"""Orchestrates one manual DEMO execution end to end.

    request -> validation -> decision -> execution -> result -> reconciliation

Every stage is persisted to the audit trail before the next begins, so a refusal
is as fully recorded as a fill. Alerts are emitted through the existing Phase 9
AlertRouter, so execution events land in the same store as everything else.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config.settings import Settings, get_settings
from database.repositories.execution import ExecutionRepository
from execution.mt5.execution_client import MT5ExecutionClient
from execution.mt5.execution_guard import ExecutionGuard, GuardContext, GuardDecision
from execution.mt5.kill_switch import ExecutionKillSwitch
from execution.mt5.order_request import ExecutionIntent, OrderRequest
from execution.mt5.order_result import ExecutionStatus, OrderResult, RejectionReason
from execution.mt5.reconciliation import Reconciler, ReconciliationRecord, ReconciliationStatus

logger = logging.getLogger(__name__)

STAGE_REQUEST = "REQUEST"
STAGE_VALIDATION = "VALIDATION"
STAGE_DECISION = "DECISION"
STAGE_EXECUTION = "EXECUTION"
STAGE_RESULT = "RESULT"
STAGE_RECONCILIATION = "RECONCILIATION"


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    request: OrderRequest
    decision: GuardDecision
    result: OrderResult
    reconciliation: ReconciliationRecord | None = None
    position: Any = None
    alerts: tuple[Any, ...] = field(default_factory=tuple)

    @property
    def executed(self) -> bool:
        return self.result.accepted

    def as_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.as_dict(),
            "decision": self.decision.as_dict(),
            "result": self.result.as_dict(),
            "reconciliation": self.reconciliation.as_dict() if self.reconciliation else None,
            "position": self.position.as_dict() if hasattr(self.position, "as_dict") else None,
            "executed": self.executed,
        }


class DemoExecutionService:
    def __init__(self, session, *, guard: ExecutionGuard | None = None,
                 client: MT5ExecutionClient | None = None,
                 read_client: Any = None, repository: ExecutionRepository | None = None,
                 reconciler: Reconciler | None = None, alerts: Any = None,
                 settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.session = session
        self.repository = repository or ExecutionRepository(session)
        self.guard = guard or ExecutionGuard(self.settings)
        self.read_client = read_client
        self.client = client or MT5ExecutionClient(self.settings, read_client=read_client)
        self.reconciler = reconciler or Reconciler()
        self.alerts = alerts

    @property
    def kill_switch(self) -> ExecutionKillSwitch:
        return self.guard.kill_switch

    # ------------------------------------------------------------------ context
    def build_context(self, request: OrderRequest, **overrides: Any) -> GuardContext:
        """Gather live state for the guard. Anything unavailable stays unsafe."""
        account = None
        quote = None
        connected = False
        known: tuple[str, ...] = ()
        open_positions = 0

        client = self.read_client
        if client is not None:
            connected = bool(client.is_connected())
            account_result = client.get_account()
            # On a REAL account the read client refuses and disconnects, but it keeps
            # the account object. Use it so the guard can report ACCOUNT_IS_REAL rather
            # than the vaguer ACCOUNT_UNAVAILABLE.
            account = account_result.data if account_result.ok else getattr(client, "account", None)
            tick = client.get_tick(request.symbol)
            quote = tick.data if tick.ok else None
            known = tuple(self.settings.demo_execution_symbol_allowlist) or tuple(
                getattr(client, "canonical_symbols", ()))
            positions = client.get_positions()
            open_positions = len(positions.data) if positions.ok else 0
        if account is None and self.client.module is not None:
            # A REAL account causes the read client to disconnect, which would leave
            # the guard reporting only NOT_CONNECTED. Read it directly so the audit
            # trail names ACCOUNT_IS_REAL explicitly.
            account = self.client.get_account()
            if client is None:
                connected = account is not None

        context = GuardContext(
            account=account, connected=connected, quote=quote,
            open_positions=open_positions, known_symbols=known,
            timestamp=request.timestamp,
        )
        if overrides:
            from dataclasses import replace

            context = replace(context, **overrides)
        return context

    # ------------------------------------------------------------------ alerts
    def _alert(self, method: str, **kwargs: Any) -> tuple[Any, ...]:
        if self.alerts is None:
            return ()
        handler = getattr(self.alerts, method, None)
        if handler is None:
            return ()
        try:
            return tuple(handler(**kwargs) or ())
        except Exception:
            logger.exception("execution alert %s failed", method)
            return ()

    # --------------------------------------------------------------- execution
    def execute(self, request: OrderRequest, context: GuardContext | None = None) -> ExecutionOutcome:
        """Run the full pipeline for one request. Never raises on a refusal."""
        environment = self.settings.environment
        self.repository.save_request(request, environment=environment)
        self.repository.save_audit(request.request_id, STAGE_REQUEST, request.as_dict(),
                                   actor="operator", environment=environment)

        context = context or self.build_context(request)
        decision = self.guard.evaluate(request, context)
        self.repository.save_audit(request.request_id, STAGE_VALIDATION, decision.as_dict(),
                                   approved=decision.approved, reasons=decision.reasons,
                                   environment=environment)

        if not decision.approved:
            result = OrderResult.blocked_by(request, decision.reasons, environment=environment)
            self.repository.save_audit(request.request_id, STAGE_DECISION,
                                       {"approved": False, "reasons": list(decision.reasons)},
                                       approved=False, reasons=decision.reasons,
                                       environment=environment)
            self.repository.save_result(result)
            self.repository.save_audit(request.request_id, STAGE_RESULT, result.as_dict(),
                                       approved=False, reasons=decision.reasons,
                                       environment=environment)
            alerts = self._alert("order_rejected", request=request, result=result,
                                 reasons=decision.reasons)
            return ExecutionOutcome(request, decision, result, None, None, alerts)

        self.repository.save_audit(request.request_id, STAGE_DECISION, {"approved": True},
                                   approved=True, environment=environment)
        alerts = self._alert("order_submitted", request=request)

        result = self.client.send_market_order(request, decision)
        self.repository.save_audit(request.request_id, STAGE_EXECUTION,
                                   {"transmitted": True, "status": str(result.status)},
                                   approved=result.accepted, environment=environment)
        self.repository.save_result(result)
        self.repository.save_audit(request.request_id, STAGE_RESULT, result.as_dict(),
                                   approved=result.accepted, reasons=result.reasons,
                                   environment=environment)

        if result.accepted:
            alerts += self._alert("order_filled", request=request, result=result)
        else:
            alerts += self._alert("order_rejected", request=request, result=result,
                                  reasons=result.reasons or (result.error_code or "UNKNOWN",))

        position = None
        if result.broker_ticket is not None:
            position = self.client.get_position(result.broker_ticket)
        record = self.reconciler.reconcile(request, result, position)
        self.repository.save_reconciliation(record)
        self.repository.save_audit(request.request_id, STAGE_RECONCILIATION, record.as_dict(),
                                   approved=record.matched, reasons=record.reasons,
                                   environment=environment)
        if record.status is ReconciliationStatus.MISMATCHED or (
            record.status is ReconciliationStatus.POSITION_MISSING
        ):
            alerts += self._alert("reconciliation_failed", record=record)

        return ExecutionOutcome(request, decision, result, record, position, alerts)

    # ------------------------------------------------------------ kill switch
    def engage_kill_switch(self, reason: str = "MANUAL_ENGAGE", *, actor: str = "operator") -> dict[str, Any]:
        event = self.kill_switch.engage(reason, actor=actor)
        self.repository.save_kill_switch_event(event)
        self._alert("execution_kill_switch", enabled=True, reason=reason)
        return self.kill_switch.status()

    def release_kill_switch(self, reason: str, *, actor: str = "operator") -> dict[str, Any]:
        event = self.kill_switch.release(reason, actor=actor)
        self.repository.save_kill_switch_event(event)
        self._alert("execution_kill_switch", enabled=False, reason=reason)
        return self.kill_switch.status()

    # ---------------------------------------------------------------- dashboard
    def status(self) -> dict[str, Any]:
        settings = self.settings
        latest_request = self.repository.latest_request()
        latest_result = self.repository.latest_result()
        latest_reconciliation = self.repository.latest_reconciliation()
        blocked_by = []
        if settings.environment != "DEMO":
            blocked_by.append(RejectionReason.ENVIRONMENT_NOT_DEMO)
        if settings.live_trading_enabled:
            blocked_by.append(RejectionReason.LIVE_TRADING_ENABLED)
        if not settings.demo_trading_enabled:
            blocked_by.append(RejectionReason.DEMO_TRADING_DISABLED)
        if not settings.mt5_execution_enabled:
            blocked_by.append(RejectionReason.MT5_EXECUTION_DISABLED)
        if settings.mt5_read_only:
            blocked_by.append(RejectionReason.MT5_READ_ONLY)
        if self.kill_switch.engaged:
            blocked_by.append(RejectionReason.KILL_SWITCH_ENGAGED)

        return {
            "environment": settings.environment,
            "execution_mode": "MANUAL_DEMO_TEST",
            "execution_state": "EXECUTION_ENABLED" if not blocked_by else "EXECUTION_BLOCKED",
            "blocked_by": [str(reason) for reason in blocked_by],
            "kill_switch": self.kill_switch.status(),
            "gates": {
                "demo_trading_enabled": settings.demo_trading_enabled,
                "mt5_execution_enabled": settings.mt5_execution_enabled,
                "mt5_read_only": settings.mt5_read_only,
                "live_trading_enabled": settings.live_trading_enabled,
            },
            "automated_trading": False,
            "strategy_auto_execution": False,
            "last_order": _row_to_dict(latest_request),
            "last_order_result": _row_to_dict(latest_result),
            "reconciliation": _row_to_dict(latest_reconciliation),
            "timestamp": datetime.now(timezone.utc),
        }


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
