"""ControlledDemoTradingService — the Phase 16 entry point.

One request walks one path:

    mode -> idempotency -> sizing -> gate chain -> proposal
         -> (human approval, in DEMO_MANUAL_APPROVAL)
         -> ExecutionGuard approval -> MT5 DEMO -> result -> reconciliation
         -> journal -> daily risk -> emergency check

Everything before the broker call is recorded before the next stage begins, so a
refusal is as fully audited as a fill. The service never raises for a market or
configuration condition: it returns an outcome whose state says what happened.

The broker call itself is delegated to the Phase 11 `MT5ExecutionClient`, which
still refuses to transmit without a matching `GuardDecision`. Phase 16 adds gates
in front of that; it does not add a second way to reach the wire.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from config.settings import Settings, get_settings
from database.repositories.execution import ExecutionRepository
from execution.demo.approval import ExecutionProposal, ManualApprovalQueue
from execution.demo.comparison import ExecutionComparator
from execution.demo.daily_risk import DailyRiskTracker
from execution.demo.emergency import EmergencyController, EmergencySignals
from execution.demo.feedback import DemoFeedbackPublisher
from execution.demo.gates import (
    DemoExecutionContext, DemoGateChain, GateChainDecision, MODE_BLOCKS_EXECUTION,
)
from execution.demo.idempotency import IdempotencyRegistry
from execution.demo.journal import DemoTradeJournal
from execution.demo.limits import (
    MAX_DAILY_LOSS, MAX_SLIPPAGE, MAX_SPREAD, MAX_TOTAL_DRAWDOWN, DemoRiskLimits,
)
from execution.demo.modes import ExecutionMode, ExecutionModeResolver
from execution.demo.monitor import PositionMonitor
from execution.demo.order import DemoOrderRequest
from execution.demo.performance import calculate_demo_performance
from execution.demo.sizing import PositionSize, PositionSizer, SymbolContract
from execution.demo.states import DemoExecutionState, ExecutionLifecycle, state_for_result
from execution.mt5.execution_client import MT5ExecutionClient
from execution.mt5.execution_guard import ExecutionGuard
from execution.mt5.kill_switch import ExecutionKillSwitch
from execution.mt5.order_result import ExecutionStatus, OrderResult
from execution.mt5.reconciliation import Reconciler, ReconciliationStatus
from observation.demo_account import DemoAccountValidator
from validation.circuit_breaker import CIRCUIT_BREAKER_OPEN, BreakerSignals, CircuitBreaker
from validation.shadow import NOT_EXECUTED_MODE, NOT_EXECUTED_PENDING, ShadowRecorder

logger = logging.getLogger(__name__)

STAGE_MODE = "MODE"
STAGE_IDEMPOTENCY = "IDEMPOTENCY"
STAGE_SIZING = "SIZING"
STAGE_GATES = "GATES"
STAGE_PROPOSAL = "PROPOSAL"
STAGE_APPROVAL = "APPROVAL"
STAGE_EXECUTION = "EXECUTION"
STAGE_RESULT = "RESULT"
STAGE_RECONCILIATION = "RECONCILIATION"
STAGE_EMERGENCY = "EMERGENCY"
STAGE_SHADOW = "SHADOW"


@dataclass(frozen=True, slots=True)
class DemoExecutionOutcome:
    request: DemoOrderRequest
    state: DemoExecutionState
    decision: GateChainDecision | None = None
    proposal: ExecutionProposal | None = None
    result: OrderResult | None = None
    reconciliation: Any = None
    position: Any = None
    lifecycle: ExecutionLifecycle | None = None
    reasons: tuple[str, ...] = ()
    alerts: tuple[Any, ...] = ()
    sizing: PositionSize | None = None

    @property
    def executed(self) -> bool:
        return self.result is not None and self.result.accepted

    @property
    def approved(self) -> bool:
        return self.decision is not None and self.decision.approved

    def as_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.as_dict(), "state": str(self.state),
            "approved": self.approved, "executed": self.executed,
            "reasons": list(self.reasons),
            "decision": self.decision.as_dict() if self.decision else None,
            "proposal": self.proposal.as_dict() if self.proposal else None,
            "result": self.result.as_dict() if self.result else None,
            "reconciliation": self.reconciliation.as_dict() if self.reconciliation else None,
            "position": self.position.as_dict() if hasattr(self.position, "as_dict") else None,
            "sizing": self.sizing.as_dict() if self.sizing else None,
            "lifecycle": self.lifecycle.as_dict() if self.lifecycle else None,
        }


class ControlledDemoTradingService:
    def __init__(self, session: Any, *, settings: Settings | None = None,
                 chain: DemoGateChain | None = None, guard: ExecutionGuard | None = None,
                 client: MT5ExecutionClient | None = None, read_client: Any = None,
                 repository: ExecutionRepository | None = None,
                 demo_repository: Any = None, alerts: Any = None,
                 limits: DemoRiskLimits | None = None,
                 approvals: ManualApprovalQueue | None = None,
                 daily: DailyRiskTracker | None = None,
                 reconciler: Reconciler | None = None,
                 emergency: EmergencyController | None = None,
                 feedback: DemoFeedbackPublisher | None = None,
                 journal: DemoTradeJournal | None = None,
                 monitor: PositionMonitor | None = None,
                 idempotency: IdempotencyRegistry | None = None,
                 counters: dict[str, int] | None = None,
                 shadow: ShadowRecorder | None = None,
                 breaker: CircuitBreaker | None = None,
                 validation_repository: Any = None):
        self.settings = settings or get_settings()
        self.session = session
        self.repository = repository or (ExecutionRepository(session) if session is not None else None)
        self.demo_repository = demo_repository
        self.guard = guard or (chain.guard if chain is not None else ExecutionGuard(self.settings))
        self.limits = limits or DemoRiskLimits.from_config()
        self.chain = chain or DemoGateChain(self.settings, guard=self.guard, limits=self.limits)
        self.read_client = read_client
        self.client = client or MT5ExecutionClient(self.settings, read_client=read_client)
        self.alerts = alerts
        self.modes = ExecutionModeResolver(self.settings)
        self.sizer = PositionSizer(self.limits)
        # The registry, queue, journal and monitor outlive one request when the
        # caller supplies them: an approval given in one HTTP request has to be
        # visible to the submission that follows it.
        self.idempotency = idempotency or IdempotencyRegistry(self.repository)
        self.approvals = approvals or ManualApprovalQueue(repository=demo_repository)
        self.daily = daily or DailyRiskTracker(limits=self.limits)
        self.reconciler = reconciler or Reconciler()
        self.journal = journal or DemoTradeJournal(demo_repository)
        self.monitor = monitor or PositionMonitor()
        self.comparator = ExecutionComparator()
        self.feedback = feedback or DemoFeedbackPublisher(demo_repository, alerts=alerts)
        self.account_validator = DemoAccountValidator(self.settings, require_permissions=True)
        # Phase 17. The recorder is on whatever the mode is: it cannot send
        # anything, and a DEMO candidate without a shadow record would break the
        # parity the whole validation rests on.
        self.validation_repository = validation_repository
        if self.validation_repository is None and session is not None:
            from database.repositories.validation import ValidationRepository

            self.validation_repository = ValidationRepository(session)
        self.shadow = shadow or ShadowRecorder(self.validation_repository)
        self.breaker = breaker or CircuitBreaker(
            self.settings, kill_switch=self.guard.kill_switch, alerts=alerts,
            repository=self.validation_repository, limits=self.limits)
        # The demo repository writes both the emergency event and the kill-switch
        # transition; the execution repository is the fallback when there is none.
        self.emergency = emergency or EmergencyController(
            self.settings, kill_switch=self.kill_switch, limits=self.limits,
            alerts=alerts, repository=self.demo_repository or self.repository)
        self._lifecycles: dict[str, ExecutionLifecycle] = {}
        # Shared with the caller when supplied, for the same reason as the queue
        # above: an API that builds a service per request would otherwise report
        # a submitted count of zero immediately after submitting.
        self.counters = counters if counters is not None else {}
        for name in ("submitted", "rejected", "execution_errors", "reconciliation_failures"):
            self.counters.setdefault(name, 0)
        # Arming DEMO execution is announced once, not once per order.
        self._announced_mode: str | None = None

    # ------------------------------------------------------------------ state
    @property
    def kill_switch(self) -> ExecutionKillSwitch:
        return self.guard.kill_switch

    @property
    def mode(self) -> ExecutionMode:
        return self.modes.resolve().mode

    def _audit(self, request_id: str, stage: str, payload: Any, *, approved: bool | None = None,
               reasons: Any = (), actor: str = "system") -> None:
        if self.repository is None:
            return
        try:
            self.repository.save_audit(request_id, stage, payload, approved=approved,
                                       reasons=reasons, actor=actor,
                                       environment=self.settings.environment)
        except Exception:
            logger.exception("failed to audit stage %s for %s", stage, request_id)

    def _alert(self, method: str, **kwargs: Any) -> tuple[Any, ...]:
        if self.alerts is None:
            return ()
        handler = getattr(self.alerts, method, None)
        if handler is None:
            return ()
        try:
            return tuple(handler(**kwargs) or ())
        except Exception:
            logger.exception("demo execution alert %s failed", method)
            return ()

    def _lifecycle(self, request_id: str, *, state: DemoExecutionState,
                   reasons: tuple[str, ...] = ()) -> ExecutionLifecycle:
        lifecycle = self._lifecycles.get(request_id)
        if lifecycle is None:
            lifecycle = ExecutionLifecycle(request_id, state=state, reasons=reasons)
            self._lifecycles[request_id] = lifecycle
        return lifecycle

    def lifecycle_for(self, request_id: str) -> ExecutionLifecycle | None:
        return self._lifecycles.get(str(request_id))

    # ---------------------------------------------------------------- sizing
    def size(self, *, symbol: str, entry_price: float, stop_loss: float | None,
             equity: float | None = None, risk_percent: float | None = None,
             contract: SymbolContract | None = None, open_symbol_exposure: float = 0.0,
             open_total_exposure: float = 0.0, free_margin: float | None = None) -> PositionSize:
        """Derive a volume. Callers never pass a lot size into `submit`."""
        account = self._account()
        resolved_equity = equity if equity is not None else (
            float(account.equity) if account is not None else 0.0)
        resolved_margin = free_margin if free_margin is not None else (
            float(account.free_margin) if account is not None else None)
        return self.sizer.calculate(
            symbol=symbol, equity=resolved_equity, entry_price=entry_price, stop_loss=stop_loss,
            contract=contract, risk_percent=risk_percent,
            open_symbol_exposure=open_symbol_exposure, open_total_exposure=open_total_exposure,
            free_margin=resolved_margin)

    # --------------------------------------------------------------- context
    def _account(self) -> Any:
        client = self.read_client
        if client is not None:
            result = client.get_account()
            account = result.data if getattr(result, "ok", False) else getattr(client, "account", None)
            if account is not None:
                return account
        return self.client.get_account()

    def build_context(self, request: DemoOrderRequest, **overrides: Any) -> DemoExecutionContext:
        """Gather live state. Anything unavailable stays unsafe."""
        client = self.read_client
        connected = bool(client.is_connected()) if client is not None else False
        account_result = self.account_validator.validate_client(client) if client is not None else None
        account = account_result.account if account_result is not None else self._account()

        quote = None
        known: tuple[str, ...] = ()
        positions: list[Any] = []
        if client is not None:
            tick = client.get_tick(request.symbol)
            quote = tick.data if tick.ok else None
            known = tuple(self.settings.demo_execution_symbol_allowlist) or tuple(
                getattr(client, "canonical_symbols", ()))
            read = client.get_positions()
            positions = list(read.data) if read.ok else []

        equity = float(getattr(account, "equity", 0.0) or 0.0)
        daily = self.daily.update(equity=equity, moment=request.timestamp) if equity else None
        symbol_exposure = sum(
            float(position.volume) * float(position.open_price) * 100_000.0
            for position in positions if position.symbol == request.symbol)
        total_exposure = sum(
            float(position.volume) * float(position.open_price) * 100_000.0
            for position in positions)

        context = DemoExecutionContext(
            account=account_result, connected=connected, quote=quote,
            equity=equity or None,
            free_margin=float(getattr(account, "free_margin", 0.0) or 0.0) or None,
            used_margin=float(getattr(account, "margin", 0.0) or 0.0),
            daily=daily, open_positions=len(positions),
            symbol_exposure=symbol_exposure, total_exposure=total_exposure,
            order_notional=float(request.volume) * float(request.price or 0.0) * 100_000.0,
            known_symbols=known, timestamp=request.timestamp,
            idempotency=self.idempotency.check(request.request_id),
            mode=self.modes.resolve())
        if overrides:
            from dataclasses import replace

            context = replace(context, **overrides)
        return context

    # -------------------------------------------------------------- proposal
    def propose(self, request: DemoOrderRequest,
                context: DemoExecutionContext | None = None) -> DemoExecutionOutcome:
        """Run the gates and record a proposal. Sends nothing, in any mode."""
        from dataclasses import replace

        environment = self.settings.environment
        # Before anything is written: recording the request first would make the
        # service find its own row and call every submission a duplicate.
        verdict = self.idempotency.check(request.request_id)
        if self.repository is not None:
            try:
                self.repository.save_request(request.to_order_request(), environment=environment)
            except Exception:
                logger.exception("failed to persist demo request %s", request.request_id)
        self._audit(request.request_id, STAGE_MODE, self.modes.resolve().as_dict(), actor="system")

        context = context if context is not None else self.build_context(request)
        context = replace(context, idempotency=verdict)
        if not verdict.allowed:
            self._audit(request.request_id, STAGE_IDEMPOTENCY, verdict.as_dict(),
                        approved=False, reasons=verdict.reasons)
            self._alert("duplicate_order_blocked", request=request, verdict=verdict)
        decision = self.chain.evaluate(request, context)
        self._audit(request.request_id, STAGE_GATES, decision.as_dict(),
                    approved=decision.approved, reasons=decision.reasons)

        proposal = self.approvals.propose(request, decision, now=request.timestamp,
                                          mode=str(decision.mode.mode) if decision.mode else "")
        self._audit(request.request_id, STAGE_PROPOSAL, proposal.as_dict(),
                    approved=decision.approved, reasons=decision.reasons)

        # Section 3: every DEMO candidate produces a shadow record, minted from
        # the decision that was just made rather than recomputed. That is what
        # makes SHADOW and DEMO the same pipeline instead of two that agree.
        shadow_signal = None
        if getattr(self.settings, "shadow_mode_enabled", True):
            waiting = (decision.approved and decision.mode is not None
                       and decision.mode.requires_human_approval)
            shadow_signal = self.shadow.record(
                request, decision, context,
                not_executed_reason=NOT_EXECUTED_PENDING if waiting else None)
            self._audit(request.request_id, STAGE_SHADOW, shadow_signal.as_dict(),
                        approved=decision.approved, reasons=decision.reasons)

        state = DemoExecutionState.PROPOSED if decision.approved else DemoExecutionState.BLOCKED
        lifecycle = self._lifecycle(request.request_id, state=state, reasons=decision.reasons)
        alerts: tuple[Any, ...] = self._announce_mode(decision.mode, context)
        if not decision.approved:
            self.counters["rejected"] += 1
            alerts += self._alert("order_blocked", request=request, reasons=decision.reasons)
            if "ACCOUNT_IS_REAL" in decision.reasons:
                alerts += self._alert("real_account_blocked", account=context.account,
                                      reasons=decision.reasons)
            alerts += self._announce_limits(request, decision)
            if MODE_BLOCKS_EXECUTION in decision.reasons:
                alerts += self._alert("execution_disabled", reasons=decision.reasons)
            self._persist_blocked_result(request, decision)
        elif decision.mode is not None and decision.mode.requires_human_approval:
            alerts += self._alert("manual_approval_required", proposal=proposal)
        return DemoExecutionOutcome(request, state, decision, proposal, None, None, None,
                                    lifecycle, decision.reasons, alerts)

    def _announce_mode(self, mode: Any, context: DemoExecutionContext) -> tuple[Any, ...]:
        """Raise DEMO_EXECUTION_ENABLED the first time a broker mode is in use.

        Arming DEMO execution is the most consequential configuration change this
        system supports, so it is announced as loudly as a refusal — once.
        """
        if mode is None or not mode.sends_orders:
            return ()
        name = str(mode.mode)
        if self._announced_mode == name:
            return ()
        self._announced_mode = name
        account = context.account.account if context.account else None
        return self._alert("demo_execution_enabled", mode=name, account=account)

    def _announce_limits(self, request: DemoOrderRequest,
                         decision: GateChainDecision) -> tuple[Any, ...]:
        """One alert per risk limit that actually fired, not one per refusal."""
        alerts: tuple[Any, ...] = ()
        for code in (MAX_DAILY_LOSS, MAX_TOTAL_DRAWDOWN, MAX_SPREAD, MAX_SLIPPAGE):
            if code in decision.reasons:
                alerts += self._alert("risk_limit_reached", limit=code, symbol=request.symbol)
        return alerts

    def _persist_blocked_result(self, request: DemoOrderRequest, decision: GateChainDecision,
                                *, extra_reasons: tuple[str, ...] = ()) -> OrderResult:
        reasons = tuple(decision.reasons) + tuple(extra_reasons)
        result = OrderResult.blocked_by(request.to_order_request(), reasons,
                                        environment=self.settings.environment)
        if self.repository is not None:
            try:
                self.repository.save_result(result)
            except Exception:
                logger.exception("failed to persist blocked result %s", request.request_id)
        self._audit(request.request_id, STAGE_RESULT, result.as_dict(), approved=False,
                    reasons=reasons)
        return result

    # --------------------------------------------------------------- approval
    def approve(self, proposal_id: str, *, approved_by: str, reason: str,
                now: datetime | None = None) -> DemoExecutionOutcome:
        """Approve a pending proposal and submit it. The human is named in the audit."""
        proposal = self.approvals.approve(proposal_id, approved_by=approved_by, reason=reason,
                                          now=now)
        self._audit(proposal.request.request_id, STAGE_APPROVAL,
                    {"approved_by": approved_by, "reason": reason},
                    approved=True, actor=str(approved_by))
        lifecycle = self._lifecycle(proposal.request.request_id,
                                    state=DemoExecutionState.PROPOSED)
        if lifecycle.state is DemoExecutionState.PROPOSED:
            lifecycle.advance(DemoExecutionState.APPROVED, actor=str(approved_by),
                              reasons=(reason,))
        return self._transmit(proposal.request, proposal.decision, proposal=proposal,
                              lifecycle=lifecycle, actor=str(approved_by))

    def reject(self, proposal_id: str, *, reason: str, actor: str = "operator") -> ExecutionProposal:
        proposal = self.approvals.reject(proposal_id, reason=reason, actor=actor)
        self._audit(proposal.request.request_id, STAGE_APPROVAL,
                    {"rejected": True, "reason": reason}, approved=False, actor=actor)
        lifecycle = self._lifecycle(proposal.request.request_id, state=DemoExecutionState.PROPOSED)
        if lifecycle.can_advance(DemoExecutionState.CANCELLED):
            lifecycle.advance(DemoExecutionState.CANCELLED, actor=actor, reasons=(reason,))
        return proposal

    # -------------------------------------------------------------- execution
    def submit(self, request: DemoOrderRequest,
               context: DemoExecutionContext | None = None) -> DemoExecutionOutcome:
        """The full path for one request.

        In DEMO_MANUAL_APPROVAL this stops at the proposal — deliberately. The
        mode exists so the whole path can be exercised with a human in it, and a
        service that quietly submitted anyway would defeat the mode.
        """
        outcome = self.propose(request, context)
        if not outcome.approved:
            return outcome

        mode = self.modes.resolve()
        if mode.mode is not ExecutionMode.DEMO_AUTOMATED:
            reasons = outcome.reasons or (MODE_BLOCKS_EXECUTION,)
            if mode.requires_human_approval:
                # Approved by the gates, waiting on a person.
                return outcome
            return DemoExecutionOutcome(request, DemoExecutionState.BLOCKED, outcome.decision,
                                        outcome.proposal, None, None, None, outcome.lifecycle,
                                        reasons + (MODE_BLOCKS_EXECUTION,), outcome.alerts)

        lifecycle = outcome.lifecycle or self._lifecycle(request.request_id,
                                                         state=DemoExecutionState.PROPOSED)
        if lifecycle.state is DemoExecutionState.PROPOSED:
            lifecycle.advance(DemoExecutionState.APPROVED, actor="automation")
        return self._transmit(request, outcome.decision, proposal=outcome.proposal,
                              lifecycle=lifecycle, actor="automation")

    def _transmit(self, request: DemoOrderRequest, decision: GateChainDecision | None, *,
                  proposal: ExecutionProposal | None = None,
                  lifecycle: ExecutionLifecycle | None = None,
                  actor: str = "system") -> DemoExecutionOutcome:
        """The only place a Phase 16 order reaches the broker."""
        lifecycle = lifecycle or self._lifecycle(request.request_id,
                                                 state=DemoExecutionState.APPROVED)
        if decision is None or decision.guard is None or not decision.approved:
            reasons = decision.reasons if decision else ("GATE_DECISION_MISSING",)
            result = self._persist_blocked_result(request, decision) if decision else None
            if lifecycle.can_advance(DemoExecutionState.BLOCKED):
                lifecycle.advance(DemoExecutionState.BLOCKED, actor=actor, reasons=reasons)
            return DemoExecutionOutcome(request, DemoExecutionState.BLOCKED, decision, proposal,
                                        result, None, None, lifecycle, tuple(reasons))

        if self.breaker.open:
            # Independent of the kill switch on purpose: releasing the switch must
            # not be a way around the section 23 recovery checklist.
            reasons = self.breaker.blocking_reasons()
            result = self._persist_blocked_result(request, decision, extra_reasons=reasons)
            if lifecycle.can_advance(DemoExecutionState.BLOCKED):
                lifecycle.advance(DemoExecutionState.BLOCKED, actor=actor, reasons=reasons)
            return DemoExecutionOutcome(request, DemoExecutionState.BLOCKED, decision, proposal,
                                        result, None, None, lifecycle, reasons)

        self.idempotency.register(request.request_id, moment=request.timestamp)
        self.daily.record_trade()
        self.counters["submitted"] += 1
        if lifecycle.can_advance(DemoExecutionState.SUBMITTED):
            lifecycle.advance(DemoExecutionState.SUBMITTED, actor=actor)
        alerts = self._alert("order_submitted", request=request.to_order_request())

        order = request.to_order_request()
        result = self.client.send_market_order(order, decision.guard)
        self._audit(request.request_id, STAGE_EXECUTION,
                    {"transmitted": True, "status": str(result.status)},
                    approved=result.accepted, actor=actor)
        if self.repository is not None:
            try:
                self.repository.save_result(result)
            except Exception:
                logger.exception("failed to persist result %s", request.request_id)
        self._audit(request.request_id, STAGE_RESULT, result.as_dict(),
                    approved=result.accepted, reasons=result.reasons, actor=actor)

        state = state_for_result(result)
        if lifecycle.can_advance(state):
            lifecycle.advance(state, actor=actor, reasons=result.reasons)
        if result.accepted:
            alerts += self._alert("order_filled", request=order, result=result)
        else:
            self.counters["rejected"] += 1
            if result.status is ExecutionStatus.FAILED:
                self.counters["execution_errors"] += 1
            alerts += self._alert("order_rejected", request=order, result=result,
                                  reasons=result.reasons or (result.error_code or "UNKNOWN",))

        position = None
        if result.broker_ticket is not None:
            position = self.client.get_position(result.broker_ticket)
            if position is not None:
                self.monitor.update(position)
        record = self.reconciler.reconcile(order, result, position)
        if self.repository is not None:
            try:
                self.repository.save_reconciliation(record)
            except Exception:
                logger.exception("failed to persist reconciliation %s", request.request_id)
        self._audit(request.request_id, STAGE_RECONCILIATION, record.as_dict(),
                    approved=record.matched, reasons=record.reasons, actor=actor)

        if record.status in {ReconciliationStatus.MISMATCHED, ReconciliationStatus.POSITION_MISSING}:
            self.counters["reconciliation_failures"] += 1
            alerts += self._alert("reconciliation_failure", record=record)
            # Section 15 + 17: a reconciliation failure is a safe shutdown, so the
            # kill switch is engaged before anything else can be submitted.
            self.check_emergency(reconciliation_failures=self.counters["reconciliation_failures"])
        elif record.matched and lifecycle.can_advance(DemoExecutionState.RECONCILED):
            lifecycle.advance(DemoExecutionState.RECONCILED, actor="reconciler")

        if result.accepted:
            self.journal.open(request=request, result=result, decision=decision)
            # The shadow twin is now a paired observation rather than a
            # counterfactual, and section 6 can compare the two.
            self.shadow.mark_executed(request.request_id)
        if proposal is not None:
            self.approvals.mark(proposal.proposal_id, lifecycle.state)

        return DemoExecutionOutcome(request, lifecycle.state, decision, proposal, result, record,
                                    position, lifecycle, tuple(result.reasons), alerts)

    # -------------------------------------------------------------- emergency
    def check_emergency(self, **overrides: Any) -> Any:
        """Evaluate the shutdown conditions with what the service already knows."""
        daily = self.daily.state
        account = self._account()
        signals = EmergencySignals(
            daily_drawdown=daily.daily_drawdown if daily else None,
            total_drawdown=daily.total_drawdown if daily else None,
            execution_errors=self.counters["execution_errors"],
            connected=bool(self.read_client.is_connected()) if self.read_client is not None else True,
            reconciliation_failures=self.counters["reconciliation_failures"],
            account_type=str(getattr(account, "trade_mode", "")) or None,
            broker=getattr(account, "broker", None),
            expected_broker=self.settings.mt5_broker,
            server=getattr(account, "server", None),
            expected_server=self.settings.mt5_server,
        )
        if overrides:
            from dataclasses import replace

            signals = replace(signals, **overrides)
        decision = self.emergency.check(signals)
        self.breaker.check(BreakerSignals(
            daily_drawdown=signals.daily_drawdown, total_drawdown=signals.total_drawdown,
            reconciliation_failures=signals.reconciliation_failures,
            execution_failures=signals.execution_errors,
            data_age_seconds=signals.data_age_seconds, model_failed=signals.model_failed,
            risk_engine_failed=signals.risk_engine_failed,
            account_type=signals.account_type, broker=signals.broker,
            expected_broker=signals.expected_broker, spread=signals.spread,
            allowed_symbols=self.settings.demo_execution_symbol_allowlist))
        if decision.shutdown:
            self._audit("EMERGENCY", STAGE_EMERGENCY, decision.as_dict(), approved=False,
                        reasons=decision.reasons, actor="emergency")
        return decision

    # ------------------------------------------------------------ kill switch
    def engage_kill_switch(self, reason: str = "MANUAL_ENGAGE", *,
                           actor: str = "operator") -> dict[str, Any]:
        event = self.kill_switch.engage(reason, actor=actor)
        if self.repository is not None:
            self.repository.save_kill_switch_event(event)
        self._alert("execution_kill_switch", enabled=True, reason=reason)
        return self.kill_switch.status()

    def release_kill_switch(self, reason: str, *, actor: str = "operator") -> dict[str, Any]:
        event = self.kill_switch.release(reason, actor=actor)
        if self.repository is not None:
            self.repository.save_kill_switch_event(event)
        self._alert("execution_kill_switch", enabled=False, reason=reason)
        return self.kill_switch.status()

    # -------------------------------------------------------------- reporting
    def performance(self) -> dict[str, Any]:
        return calculate_demo_performance(
            self.journal.entries, orders_submitted=self.counters["submitted"],
            orders_rejected=self.counters["rejected"],
            reconciliation_errors=self.counters["reconciliation_failures"]).as_dict()

    def status(self) -> dict[str, Any]:
        """The dashboard payload (section 26)."""
        settings = self.settings
        mode = self.modes.resolve()
        account = self._account()
        daily = self.daily.state
        blocked: list[str] = list(self.modes.blocking_reasons())
        if settings.environment != "DEMO":
            blocked.append("ENVIRONMENT_NOT_DEMO")
        if settings.live_trading_enabled:
            blocked.append("LIVE_TRADING_ENABLED")
        if settings.real_account_execution:
            blocked.append("REAL_ACCOUNT_EXECUTION")
        if not settings.demo_trading_enabled:
            blocked.append("DEMO_TRADING_DISABLED")
        if not settings.mt5_execution_enabled:
            blocked.append("MT5_EXECUTION_DISABLED")
        if self.kill_switch.engaged:
            blocked.append("KILL_SWITCH_ENGAGED")
        if self.breaker.open:
            blocked.append(CIRCUIT_BREAKER_OPEN)

        last = self.journal.entries[-1] if self.journal.entries else None
        return {
            "environment": settings.environment,
            "execution_mode": str(mode.mode),
            "mode": mode.as_dict(),
            "live_trading_enabled": False,
            "real_account_execution": False,
            "execution_state": "EXECUTION_BLOCKED" if blocked else "EXECUTION_ENABLED",
            "blocked_by": list(dict.fromkeys(blocked)),
            "kill_switch": self.kill_switch.status(),
            "gates": self.chain.gate_names(),
            "limits": self.limits.as_dict(),
            "account": {
                "broker": getattr(account, "broker", settings.mt5_broker),
                "server": getattr(account, "server", settings.mt5_server),
                "login": getattr(account, "masked_login", None),
                "account_type": str(getattr(account, "trade_mode", "UNKNOWN")),
                "is_demo": str(getattr(account, "trade_mode", "")) in {"DEMO", "CONTEST"},
                "currency": getattr(account, "currency", None),
                "balance": getattr(account, "balance", None),
                "equity": getattr(account, "equity", None),
                "margin": getattr(account, "margin", None),
                "free_margin": getattr(account, "free_margin", None),
            },
            "daily_risk": daily.as_dict() if daily else None,
            "open_positions": [snapshot.as_dict() for snapshot in self.monitor.snapshots],
            "position_summary": self.monitor.summary(),
            "pending_approvals": [proposal.as_dict() for proposal in self.approvals.pending()],
            "performance": self.performance(),
            "last_trade": last.as_dict() if last else None,
            "counters": dict(self.counters),
            "circuit_breaker": self.breaker.status(),
            "shadow": self.shadow.summary(),
            "timestamp": datetime.now(timezone.utc),
        }

    # -------------------------------------------------------------- utilities
    def trading_day(self, moment: datetime | None = None) -> date:
        return self.daily.trading_day(moment or datetime.now(timezone.utc))
