from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4
class AlertType(StrEnum):
    LIQUIDITY_SWEEP="LIQUIDITY_SWEEP";BOS="BOS";CHOCH="CHOCH";MTF_CONFLICT="MTF_CONFLICT";STRATEGY_READY="STRATEGY_READY";STRATEGY_INVALIDATED="STRATEGY_INVALIDATED";DCA_TRIGGER="DCA_TRIGGER";DCA_BLOCKED="DCA_BLOCKED";EXIT_TRIGGER="EXIT_TRIGGER";RISK_WARNING="RISK_WARNING";RISK_BLOCK="RISK_BLOCK";MODEL_ERROR="MODEL_ERROR";DATA_ERROR="DATA_ERROR";PROVIDER_ERROR="PROVIDER_ERROR";PAPER_ENTRY="PAPER_ENTRY";EXECUTION_ENABLED="EXECUTION_ENABLED";EXECUTION_BLOCKED="EXECUTION_BLOCKED";ORDER_SUBMITTED="ORDER_SUBMITTED";ORDER_FILLED="ORDER_FILLED";ORDER_REJECTED="ORDER_REJECTED";RECONCILIATION_FAILED="RECONCILIATION_FAILED";KILL_SWITCH_TRIGGERED="KILL_SWITCH_TRIGGERED";MT5_CONNECTED="MT5_CONNECTED";MT5_DISCONNECTED="MT5_DISCONNECTED";DEMO_ACCOUNT_VALID="DEMO_ACCOUNT_VALID";REAL_ACCOUNT_DETECTED="REAL_ACCOUNT_DETECTED";STALE_MARKET_DATA="STALE_MARKET_DATA";DATA_QUALITY_FAILED="DATA_QUALITY_FAILED";SPREAD_TOO_HIGH="SPREAD_TOO_HIGH";KILL_SWITCH_ACTIVE="KILL_SWITCH_ACTIVE";RECONCILIATION_FAILURE="RECONCILIATION_FAILURE";STRATEGY_SIGNAL="STRATEGY_SIGNAL"
    # Phase 14: the 24/7 forward observation loop (section 26).
    OBSERVATION_DRIVER_STOPPED="OBSERVATION_DRIVER_STOPPED";OBSERVATION_CYCLE_FAILED="OBSERVATION_CYCLE_FAILED";DATA_STALE="DATA_STALE";MODEL_FAILURE="MODEL_FAILURE";LABELING_FAILURE="LABELING_FAILURE";DATASET_FAILURE="DATASET_FAILURE";MODEL_DRIFT="MODEL_DRIFT";PERFORMANCE_DEGRADATION="PERFORMANCE_DEGRADATION";HIGH_CONFIDENCE_FAILURE="HIGH_CONFIDENCE_FAILURE";NO_EDGE="NO_EDGE";EDGE_DETECTED="EDGE_DETECTED";INSUFFICIENT_DATA="INSUFFICIENT_DATA"
    # Phase 16: controlled DEMO trading (section 27).
    DEMO_EXECUTION_ENABLED="DEMO_EXECUTION_ENABLED";REAL_ACCOUNT_BLOCKED="REAL_ACCOUNT_BLOCKED";ORDER_BLOCKED="ORDER_BLOCKED";RISK_LIMIT_REACHED="RISK_LIMIT_REACHED";DAILY_LOSS_LIMIT="DAILY_LOSS_LIMIT";DRAWDOWN_LIMIT="DRAWDOWN_LIMIT";SPREAD_LIMIT="SPREAD_LIMIT";SLIPPAGE_LIMIT="SLIPPAGE_LIMIT";EXECUTION_DISABLED="EXECUTION_DISABLED";EMERGENCY_SHUTDOWN="EMERGENCY_SHUTDOWN";MANUAL_APPROVAL_REQUIRED="MANUAL_APPROVAL_REQUIRED";DUPLICATE_ORDER_BLOCKED="DUPLICATE_ORDER_BLOCKED"
    # Phase 17: shadow trading and DEMO validation (sections 21, 22, 23).
    CIRCUIT_BREAKER_TRIPPED="CIRCUIT_BREAKER_TRIPPED";CIRCUIT_BREAKER_RECOVERED="CIRCUIT_BREAKER_RECOVERED";ANOMALY_DETECTED="ANOMALY_DETECTED";PERFORMANCE_GATE_FAILED="PERFORMANCE_GATE_FAILED";SHADOW_DEMO_DIVERGENCE="SHADOW_DEMO_DIVERGENCE";AUTOMATION_ELIGIBLE="AUTOMATION_ELIGIBLE";VALIDATION_REPORT="VALIDATION_REPORT"
class AlertSeverity(StrEnum):LOW="LOW";MEDIUM="MEDIUM";HIGH="HIGH";CRITICAL="CRITICAL"
@dataclass(frozen=True,slots=True)
class Alert:
    alert_id:str;timestamp:datetime;symbol:str|None;alert_type:AlertType;severity:AlertSeverity;title:str;message:str;source:str;version:str="phase9.alerts.v1";data_quality:str="VALID";read:bool=False;context:dict[str,Any]|None=None
class NotificationProvider:
    def notify(self,alert:Alert)->None:raise NotImplementedError
class DashboardNotificationProvider(NotificationProvider):
    def __init__(self):self.alerts=[]
    def notify(self,alert):self.alerts.append(alert)
class UnavailableExternalNotificationProvider(NotificationProvider):
    def notify(self,alert):raise RuntimeError("external notification provider is not configured")
class AlertRepositoryNotificationProvider(NotificationProvider):
    """Persists alerts so emission and /dashboard/alerts share one store.

    Phase 9 originally wrote to an in-memory provider and read from a database
    repository, so nothing that was emitted was ever readable.
    """
    def __init__(self,repository):self.repository=repository
    def notify(self,alert):self.repository.add(alert)
    def list(self,*,symbol=None,alert_type=None,severity=None,unread=None):
        return self.repository.list(symbol=symbol,alert_type=alert_type,severity=severity,unread=unread)
class AlertEngine:
    def __init__(self,provider=None):self.provider=provider or DashboardNotificationProvider()
    def emit(self,alert_type,severity,title,message,*,symbol=None,source="backend",timestamp=None,context=None):
        alert=Alert(uuid4().hex,timestamp or datetime.now(timezone.utc),symbol,AlertType(alert_type),AlertSeverity(severity),title,message,source,context=context);self.provider.notify(alert);return alert
    def list(self,*,symbol=None,alert_type=None,severity=None,unread=None):
        delegate=getattr(self.provider,"list",None)
        if delegate is not None:
            return delegate(symbol=symbol,alert_type=alert_type,severity=severity,unread=unread)
        rows=list(getattr(self.provider,"alerts",[]))
        if symbol:rows=[a for a in rows if a.symbol==symbol]
        if alert_type:rows=[a for a in rows if a.alert_type.value==alert_type]
        if severity:rows=[a for a in rows if a.severity.value==severity]
        if unread is not None:rows=[a for a in rows if a.read is not unread]
        return sorted(rows,key=lambda a:a.timestamp,reverse=True)


REJECTION_ALERTS={
    "GLOBAL_KILL_SWITCH":(AlertType.RISK_BLOCK,AlertSeverity.CRITICAL),
    "DATA_QUALITY_INVALID":(AlertType.DATA_ERROR,AlertSeverity.CRITICAL),
    "PROVIDER_UNAVAILABLE":(AlertType.PROVIDER_ERROR,AlertSeverity.HIGH),
    "MODEL_FAILURE":(AlertType.MODEL_ERROR,AlertSeverity.HIGH),
}


class AlertRouter:
    """Translates domain results into alerts.

    The strategy, risk and paper layers stay unaware of alerting: whichever caller
    already holds a decision or an execution result hands it here.
    """

    def __init__(self,engine):self.engine=engine

    def _emit(self,alert_type,severity,title,message,*,symbol,timestamp,context=None,source="backend"):
        return self.engine.emit(alert_type,severity,title,message,symbol=symbol,source=source,
                                timestamp=timestamp,context=context)

    def strategy_decision(self,decision,*,timestamp=None):
        """INVALIDATE raises an alert; SIMULATE records that a setup became executable."""
        stamp=timestamp or getattr(decision,"timestamp",None)
        symbol=getattr(decision,"symbol",None)
        reasons=[str(r) for r in getattr(decision,"reason_codes",())]
        verdict=getattr(decision,"decision","")
        if verdict=="INVALIDATE":
            return [self._emit(AlertType.STRATEGY_INVALIDATED,AlertSeverity.HIGH,"Strategy invalidated",
                               ", ".join(reasons) or "STRATEGY_INVALIDATED",symbol=symbol,timestamp=stamp,
                               context={"reason_codes":reasons},source="strategy_engine")]
        if verdict=="SIMULATE":
            return [self._emit(AlertType.STRATEGY_READY,AlertSeverity.MEDIUM,"Setup executable",
                               ", ".join(reasons) or "EXECUTABLE_SIMULATION",symbol=symbol,timestamp=stamp,
                               context={"reason_codes":reasons},source="strategy_engine")]
        conflicts=[r for r in reasons if r.startswith("TIMEFRAME_CONFLICT")]
        if conflicts:
            return [self._emit(AlertType.MTF_CONFLICT,AlertSeverity.MEDIUM,"Timeframe conflict",
                               ", ".join(conflicts),symbol=symbol,timestamp=stamp,
                               context={"reason_codes":reasons},source="strategy_engine")]
        return []

    def execution_result(self,result,*,symbol,timestamp,action="ENTRY"):
        """action is ENTRY or DCA; rejections map onto the existing risk/data/provider types."""
        reasons=[str(r) for r in getattr(result,"reason_codes",())]
        context={"reason_codes":reasons,"action":action}
        if result.accepted:
            if action=="DCA":
                return [self._emit(AlertType.DCA_TRIGGER,AlertSeverity.MEDIUM,"Paper DCA executed",
                                   ", ".join(reasons) or "DCA_SIMULATION_ALLOWED",symbol=symbol,
                                   timestamp=timestamp,context=context,source="paper_engine")]
            return [self._emit(AlertType.PAPER_ENTRY,AlertSeverity.MEDIUM,"Paper entry executed",
                               ", ".join(reasons) or "PAPER_ENTRY",symbol=symbol,timestamp=timestamp,
                               context=context,source="paper_engine")]
        reason=result.rejection_reason or "ORDER_REJECTED"
        alert_type,severity=REJECTION_ALERTS.get(reason,(AlertType.RISK_BLOCK,AlertSeverity.HIGH))
        if action=="DCA" and alert_type is AlertType.RISK_BLOCK:
            alert_type=AlertType.DCA_BLOCKED
        title="Paper DCA rejected" if action=="DCA" else "Paper entry rejected"
        return [self._emit(alert_type,severity,title,reason,symbol=symbol,timestamp=timestamp,
                           context=context,source="paper_engine")]

    def paper_exit(self,position,*,reason_codes=(),timestamp=None):
        reasons=[str(r) for r in reason_codes]
        return [self._emit(AlertType.EXIT_TRIGGER,AlertSeverity.MEDIUM,"Paper position closed",
                           ", ".join(reasons) or "WHY_EXIT:PAPER_CLOSE",
                           symbol=getattr(position,"symbol",None),
                           timestamp=timestamp or getattr(position,"updated_at",None),
                           context={"position_id":getattr(position,"position_id",None),
                                    "realized_pnl":getattr(position,"realized_pnl",None),
                                    "reason_codes":reasons},source="paper_engine")]

    def data_quality_failure(self,*,symbol,detail,timestamp=None):
        return [self._emit(AlertType.DATA_ERROR,AlertSeverity.CRITICAL,"Data quality failure",str(detail),
                           symbol=symbol,timestamp=timestamp,context={"detail":str(detail)},
                           source="data_quality")]

    def provider_unavailable(self,*,provider,status,timestamp=None,symbol=None):
        return [self._emit(AlertType.PROVIDER_ERROR,AlertSeverity.HIGH,"Provider unavailable",
                           f"{provider} is {status}",symbol=symbol,timestamp=timestamp,
                           context={"provider":provider,"status":status},source="market_gateway")]

    def kill_switch(self,*,enabled,timestamp=None,symbol=None):
        severity=AlertSeverity.CRITICAL if enabled else AlertSeverity.MEDIUM
        message="GLOBAL_KILL_SWITCH_ACTIVATED" if enabled else "GLOBAL_KILL_SWITCH_RELEASED"
        return [self._emit(AlertType.RISK_BLOCK,severity,"Kill switch",message,symbol=symbol,
                           timestamp=timestamp,context={"enabled":enabled},source="paper_risk")]

    # ------------------------------------------------------ Phase 11 execution
    def order_submitted(self, *, request, timestamp=None):
        return [self._emit(AlertType.ORDER_SUBMITTED, AlertSeverity.MEDIUM, "DEMO order submitted",
                           f"{request.side} {request.volume} {request.symbol}",
                           symbol=request.symbol, timestamp=timestamp or request.timestamp,
                           context={"request_id": request.request_id, "intent": str(request.intent)},
                           source="execution")]

    def order_filled(self, *, request, result, timestamp=None):
        return [self._emit(AlertType.ORDER_FILLED, AlertSeverity.MEDIUM, "DEMO order filled",
                           f"{result.status} {result.filled_volume} {request.symbol}",
                           symbol=request.symbol, timestamp=timestamp or result.timestamp,
                           context={"request_id": request.request_id,
                                    "broker_ticket": result.broker_ticket,
                                    "filled_price": result.filled_price},
                           source="execution")]

    def order_rejected(self, *, request, result=None, reasons=(), timestamp=None):
        codes = [str(reason) for reason in reasons]
        severity = (AlertSeverity.CRITICAL
                    if any(code in {"ACCOUNT_IS_REAL", "LIVE_TRADING_ENABLED"} for code in codes)
                    else AlertSeverity.HIGH)
        return [self._emit(AlertType.ORDER_REJECTED, severity, "DEMO order rejected",
                           ", ".join(codes) or "REJECTED", symbol=request.symbol,
                           timestamp=timestamp or request.timestamp,
                           context={"request_id": request.request_id, "reasons": codes},
                           source="execution")]

    def reconciliation_failed(self, *, record, timestamp=None):
        return [self._emit(AlertType.RECONCILIATION_FAILED, AlertSeverity.HIGH,
                           "Reconciliation failed",
                           ", ".join(record.reasons) or str(record.status),
                           symbol=record.symbol, timestamp=timestamp or record.timestamp,
                           context={"request_id": record.request_id,
                                    "status": str(record.status),
                                    "differences": record.differences},
                           source="execution")]

    def execution_state(self, *, enabled, reasons=(), timestamp=None, symbol=None):
        alert_type = AlertType.EXECUTION_ENABLED if enabled else AlertType.EXECUTION_BLOCKED
        severity = AlertSeverity.MEDIUM if enabled else AlertSeverity.HIGH
        return [self._emit(alert_type, severity,
                           "Execution enabled" if enabled else "Execution blocked",
                           ", ".join(str(reason) for reason in reasons)
                           or ("EXECUTION_ENABLED" if enabled else "EXECUTION_BLOCKED"),
                           symbol=symbol, timestamp=timestamp,
                           context={"enabled": enabled,
                                    "reasons": [str(reason) for reason in reasons]},
                           source="execution")]

    def execution_kill_switch(self, *, enabled, timestamp=None, symbol=None, reason=None):
        """The Phase 11 EXECUTION kill switch.

        Distinct from `kill_switch` above, which reports the paper engine's risk
        switch. Same shape, different subsystem, so both keep their own alert type.
        """
        severity = AlertSeverity.CRITICAL if enabled else AlertSeverity.MEDIUM
        message = reason or ("GLOBAL_KILL_SWITCH_ACTIVATED" if enabled
                             else "GLOBAL_KILL_SWITCH_RELEASED")
        return [self._emit(AlertType.KILL_SWITCH_TRIGGERED, severity, "Kill switch", str(message),
                           symbol=symbol, timestamp=timestamp,
                           context={"engaged": enabled}, source="execution")]

    # ----------------------------------------------------- Phase 12 observation
    def mt5_connected(self, *, account=None, timestamp=None):
        return [self._emit(AlertType.MT5_CONNECTED, AlertSeverity.LOW, "MT5 connected",
                           "terminal connected", symbol=None, timestamp=timestamp,
                           context={"server": getattr(account, "server", None)}, source="mt5")]

    def mt5_disconnected(self, *, reasons=(), timestamp=None):
        codes = [str(reason) for reason in reasons]
        return [self._emit(AlertType.MT5_DISCONNECTED, AlertSeverity.HIGH, "MT5 disconnected",
                           ", ".join(codes) or "MT5_DISCONNECTED", symbol=None,
                           timestamp=timestamp, context={"reasons": codes}, source="mt5")]

    def demo_account_valid(self, *, account, timestamp=None):
        payload = account.as_dict() if hasattr(account, "as_dict") else {}
        detail = payload.get("account") or {}
        return [self._emit(AlertType.DEMO_ACCOUNT_VALID, AlertSeverity.LOW, "DEMO account verified",
                           f"{detail.get('broker')} {detail.get('server')}", symbol=None,
                           timestamp=timestamp,
                           context={"login": detail.get("login"), "server": detail.get("server")},
                           source="mt5")]

    def real_account_detected(self, *, account, timestamp=None):
        """The most serious alert this system can raise."""
        payload = account.as_dict() if hasattr(account, "as_dict") else {}
        return [self._emit(AlertType.REAL_ACCOUNT_DETECTED, AlertSeverity.CRITICAL,
                           "REAL account detected", "execution blocked: account is not DEMO",
                           symbol=None, timestamp=timestamp,
                           context={"status": payload.get("status")}, source="mt5")]

    def stale_market_data(self, *, symbol, reasons=(), timestamp=None):
        codes = [str(reason) for reason in reasons]
        return [self._emit(AlertType.STALE_MARKET_DATA, AlertSeverity.HIGH, "Stale market data",
                           ", ".join(codes) or "STALE_MARKET_DATA", symbol=symbol,
                           timestamp=timestamp, context={"reasons": codes},
                           source="market_gateway")]

    def data_quality_failed(self, *, symbol, failures=None, timestamp=None):
        detail = {name: list(codes) for name, codes in (failures or {}).items()}
        joined = ", ".join(f"{name}:{','.join(codes)}" for name, codes in detail.items())
        return [self._emit(AlertType.DATA_QUALITY_FAILED, AlertSeverity.CRITICAL,
                           "Data quality failed", joined or "FAILED", symbol=symbol,
                           timestamp=timestamp, context={"failures": detail},
                           source="data_quality")]

    def model_failure(self, *, symbol=None, detail="", timestamp=None):
        return [self._emit(AlertType.MODEL_ERROR, AlertSeverity.HIGH, "Model failure",
                           str(detail) or "MODEL_FAILURE", symbol=symbol, timestamp=timestamp,
                           context={"detail": str(detail)}, source="neural_inference")]

    def strategy_signal(self, *, symbol, signal, decision=None, timestamp=None):
        reasons = [str(code) for code in getattr(decision, "reason_codes", ())]
        return [self._emit(AlertType.STRATEGY_SIGNAL, AlertSeverity.MEDIUM, "Strategy signal",
                           str(signal), symbol=symbol, timestamp=timestamp,
                           context={"signal": str(signal), "reason_codes": reasons},
                           source="strategy_engine")]

    def risk_block(self, *, symbol, reasons=(), timestamp=None):
        codes = [str(reason) for reason in reasons]
        return [self._emit(AlertType.RISK_BLOCK, AlertSeverity.HIGH, "Risk blocked",
                           ", ".join(codes) or "RISK_BLOCK", symbol=symbol, timestamp=timestamp,
                           context={"reasons": codes}, source="risk_engine")]

    def execution_blocked(self, *, symbol, reasons=(), timestamp=None):
        codes = [str(reason) for reason in reasons]
        return [self._emit(AlertType.EXECUTION_BLOCKED, AlertSeverity.MEDIUM, "Execution blocked",
                           ", ".join(codes) or "EXECUTION_BLOCKED", symbol=symbol,
                           timestamp=timestamp, context={"reasons": codes}, source="execution")]

    def spread_too_high(self, *, symbol, spread=None, state=None, timestamp=None):
        return [self._emit(AlertType.SPREAD_TOO_HIGH, AlertSeverity.MEDIUM, "Spread too high",
                           f"spread={spread} state={state}", symbol=symbol, timestamp=timestamp,
                           context={"spread": spread, "state": str(state) if state else None},
                           source="market_gateway")]

    def kill_switch_active(self, *, timestamp=None, symbol=None):
        return [self._emit(AlertType.KILL_SWITCH_ACTIVE, AlertSeverity.HIGH, "Kill switch active",
                           "execution blocked by the kill switch", symbol=symbol,
                           timestamp=timestamp, context={"engaged": True}, source="execution")]

    def reconciliation_failure(self, *, record, timestamp=None):
        reasons = [str(reason) for reason in getattr(record, "reasons", ())]
        return [self._emit(AlertType.RECONCILIATION_FAILURE, AlertSeverity.HIGH,
                           "Reconciliation failure", ", ".join(reasons) or "FAILED",
                           symbol=getattr(record, "symbol", None), timestamp=timestamp,
                           context={"reasons": reasons}, source="execution")]

    # ------------------------------------------ Phase 16 controlled DEMO trading
    # Every method here reports something the execution path decided. None of
    # them can change that decision: alerting is a side channel, not a control
    # path, exactly as in Phase 14.
    def demo_execution_enabled(self, *, mode, account=None, timestamp=None):
        """Raised when a broker mode becomes active. Deliberately CRITICAL.

        Arming DEMO execution is the single most consequential configuration
        change this system supports, so it is as loud as a refusal.
        """
        return [self._emit(AlertType.DEMO_EXECUTION_ENABLED, AlertSeverity.CRITICAL,
                           "DEMO execution enabled", str(mode), symbol=None,
                           timestamp=timestamp,
                           context={"mode": str(mode),
                                    "server": getattr(account, "server", None),
                                    "live_trading_enabled": False}, source="demo_execution")]

    def real_account_blocked(self, *, account=None, reasons=(), timestamp=None):
        """The most serious alert this system can raise, alongside REAL_ACCOUNT_DETECTED."""
        codes = [str(reason) for reason in reasons]
        payload = account.as_dict() if hasattr(account, "as_dict") else {}
        return [self._emit(AlertType.REAL_ACCOUNT_BLOCKED, AlertSeverity.CRITICAL,
                           "REAL account blocked",
                           ", ".join(codes) or "execution blocked: account is not DEMO",
                           symbol=None, timestamp=timestamp,
                           context={"reasons": codes, "status": payload.get("status")},
                           source="demo_execution")]

    def order_blocked(self, *, request, reasons=(), timestamp=None):
        codes = [str(reason) for reason in reasons]
        severity = (AlertSeverity.CRITICAL
                    if any(code in {"ACCOUNT_IS_REAL", "LIVE_TRADING_ENABLED"} for code in codes)
                    else AlertSeverity.HIGH)
        return [self._emit(AlertType.ORDER_BLOCKED, severity, "DEMO order blocked",
                           ", ".join(codes) or "BLOCKED",
                           symbol=getattr(request, "symbol", None),
                           timestamp=timestamp or getattr(request, "timestamp", None),
                           context={"request_id": getattr(request, "request_id", None),
                                    "reasons": codes}, source="demo_execution")]

    def duplicate_order_blocked(self, *, request, verdict=None, timestamp=None):
        return [self._emit(AlertType.DUPLICATE_ORDER_BLOCKED, AlertSeverity.HIGH,
                           "Duplicate order blocked", "DUPLICATE_EXECUTION_REQUEST",
                           symbol=getattr(request, "symbol", None),
                           timestamp=timestamp or getattr(request, "timestamp", None),
                           context={"request_id": getattr(request, "request_id", None),
                                    # isoformat, not a datetime: the alert context
                                    # is stored as JSON.
                                    "first_seen": (first_seen.isoformat()
                                                   if (first_seen := getattr(
                                                       verdict, "first_seen", None)) else None)},
                           source="demo_execution")]

    def risk_limit_reached(self, *, limit, value=None, symbol=None, timestamp=None):
        """One method for the risk-limit family; `limit` names which one fired."""
        mapping = {"MAX_DAILY_LOSS_EXCEEDED": AlertType.DAILY_LOSS_LIMIT,
                   "MAX_TOTAL_DRAWDOWN_EXCEEDED": AlertType.DRAWDOWN_LIMIT,
                   "MAX_SPREAD_EXCEEDED": AlertType.SPREAD_LIMIT,
                   "MAX_SLIPPAGE_EXCEEDED": AlertType.SLIPPAGE_LIMIT}
        alert_type = mapping.get(str(limit), AlertType.RISK_LIMIT_REACHED)
        return [self._emit(alert_type, AlertSeverity.HIGH, "Risk limit reached", str(limit),
                           symbol=symbol, timestamp=timestamp,
                           context={"limit": str(limit), "value": value},
                           source="demo_risk")]

    def execution_disabled(self, *, reasons=(), timestamp=None):
        codes = [str(reason) for reason in reasons]
        return [self._emit(AlertType.EXECUTION_DISABLED, AlertSeverity.MEDIUM,
                           "Execution disabled", ", ".join(codes) or "EXECUTION_DISABLED",
                           symbol=None, timestamp=timestamp, context={"reasons": codes},
                           source="demo_execution")]

    def manual_approval_required(self, *, proposal, timestamp=None):
        payload = proposal.as_dict() if hasattr(proposal, "as_dict") else {}
        request = payload.get("request") or {}
        return [self._emit(AlertType.MANUAL_APPROVAL_REQUIRED, AlertSeverity.MEDIUM,
                           "Manual approval required",
                           f"{request.get('side')} {request.get('volume')} {request.get('symbol')}",
                           symbol=request.get("symbol"),
                           timestamp=timestamp or payload.get("created_at"),
                           context={"proposal_id": payload.get("proposal_id"),
                                    # isoformat: the alert context is stored as JSON.
                                    "expires_at": (expires.isoformat()
                                                   if (expires := payload.get("expires_at"))
                                                   else None)},
                           source="demo_execution")]

    def emergency_shutdown(self, *, decision, timestamp=None):
        """Automatic execution shutdown (section 17). Open positions are untouched."""
        payload = decision.as_dict() if hasattr(decision, "as_dict") else dict(decision or {})
        return [self._emit(AlertType.EMERGENCY_SHUTDOWN, AlertSeverity.CRITICAL,
                           "Emergency shutdown",
                           ", ".join(payload.get("reasons") or []) or "EXECUTION_SHUTDOWN",
                           symbol=None, timestamp=timestamp or payload.get("timestamp"),
                           context={"triggers": payload.get("triggers"),
                                    "positions_closed": False,
                                    "details": payload.get("details")},
                           source="demo_execution")]

    # ----------------------------- Phase 17 shadow trading and DEMO validation
    # As everywhere else, alerting is a side channel. None of these methods can
    # trip a breaker, pass a gate or arm automation; they report what already
    # happened.
    def circuit_breaker_tripped(self, *, event, timestamp=None):
        """Section 22. As loud as an emergency shutdown, because it is one."""
        payload = event.as_dict() if hasattr(event, "as_dict") else dict(event or {})
        return [self._emit(AlertType.CIRCUIT_BREAKER_TRIPPED, AlertSeverity.CRITICAL,
                           "Circuit breaker tripped",
                           ", ".join(payload.get("reasons") or []) or "CIRCUIT_BREAKER_OPEN",
                           symbol=None, timestamp=timestamp or payload.get("timestamp"),
                           context={"triggers": payload.get("triggers"),
                                    "positions_closed": False,
                                    "auto_reset": False}, source="circuit_breaker")]

    def circuit_breaker_recovered(self, *, event, timestamp=None):
        """Section 23. Recorded with the checklist, so recovery is auditable."""
        payload = event.as_dict() if hasattr(event, "as_dict") else dict(event or {})
        checklist = payload.get("checklist") or {}
        return [self._emit(AlertType.CIRCUIT_BREAKER_RECOVERED, AlertSeverity.MEDIUM,
                           "Circuit breaker recovered",
                           f"approved by {checklist.get('approved_by')}",
                           symbol=None, timestamp=timestamp or payload.get("timestamp"),
                           context={"checklist": checklist, "actor": payload.get("actor")},
                           source="circuit_breaker")]

    def anomaly_detected(self, *, report, timestamp=None):
        """Section 21. An anomaly is a reason to look, not a verdict."""
        payload = report.as_dict() if hasattr(report, "as_dict") else dict(report or {})
        kinds = payload.get("kinds") or []
        return [self._emit(AlertType.ANOMALY_DETECTED, AlertSeverity.MEDIUM,
                           "Anomaly detected", ", ".join(kinds) or "ANOMALY",
                           symbol=None, timestamp=timestamp,
                           context={"kinds": kinds, "skipped": payload.get("skipped"),
                                    "action": "INVESTIGATE_ONLY"}, source="validation")]

    def performance_gate_failed(self, *, report, timestamp=None):
        payload = report.as_dict() if hasattr(report, "as_dict") else dict(report or {})
        failed = list(payload.get("failed") or []) + list(payload.get("unknown") or [])
        return [self._emit(AlertType.PERFORMANCE_GATE_FAILED, AlertSeverity.HIGH,
                           "Performance gate failed", ", ".join(failed) or "GATE_FAILED",
                           symbol=None, timestamp=timestamp,
                           context={"failed": payload.get("failed"),
                                    "unknown": payload.get("unknown"),
                                    "enables_execution": False}, source="validation")]

    def shadow_demo_divergence(self, *, comparison, timestamp=None):
        payload = comparison.as_dict() if hasattr(comparison, "as_dict") else dict(comparison or {})
        return [self._emit(AlertType.SHADOW_DEMO_DIVERGENCE, AlertSeverity.MEDIUM,
                           "Shadow and DEMO diverged",
                           ", ".join(payload.get("kinds") or []) or "DIVERGENCE",
                           symbol=payload.get("symbol"), timestamp=timestamp,
                           context={"shadow_signal_id": payload.get("shadow_signal_id"),
                                    "pnl_difference": payload.get("pnl_difference"),
                                    "primary": payload.get("primary")}, source="validation")]

    def automation_eligible(self, *, eligibility, timestamp=None):
        """Eligibility is a finding. The alert says so, and changes nothing."""
        payload = (eligibility.as_dict() if hasattr(eligibility, "as_dict")
                   else dict(eligibility or {}))
        eligible = bool(payload.get("DEMO_AUTOMATION_ELIGIBLE"))
        return [self._emit(AlertType.AUTOMATION_ELIGIBLE,
                           AlertSeverity.MEDIUM if eligible else AlertSeverity.LOW,
                           "DEMO automation eligibility",
                           "ELIGIBLE" if eligible else
                           ", ".join(payload.get("missing") or payload.get("unknown") or [])
                           or "NOT_ELIGIBLE",
                           symbol=None, timestamp=timestamp,
                           context={"eligible": eligible, "missing": payload.get("missing"),
                                    "unknown": payload.get("unknown"),
                                    "automatically_enabled": False}, source="validation")]

    def validation_report(self, *, kind, report=None, timestamp=None):
        payload = report.as_dict() if hasattr(report, "as_dict") else dict(report or {})
        return [self._emit(AlertType.VALIDATION_REPORT, AlertSeverity.LOW,
                           f"{str(kind).title()} review",
                           str(payload.get("edge_status") or "INSUFFICIENT_DATA"),
                           symbol=None, timestamp=timestamp,
                           context={"kind": str(kind),
                                    "edge_status": payload.get("edge_status"),
                                    "reasons": payload.get("reasons")}, source="validation")]

    # ------------------------------------------------ Phase 14 observation loop
    # Every method here reports something the loop observed. None of them can
    # change what the loop does: alerting is a side channel, not a control path.
    def observation_driver_stopped(self, *, reason="STOPPED", timestamp=None):
        return [self._emit(AlertType.OBSERVATION_DRIVER_STOPPED, AlertSeverity.HIGH,
                           "Observation driver stopped", str(reason), symbol=None,
                           timestamp=timestamp, context={"reason": str(reason)},
                           source="observation_driver")]

    def observation_cycle_failed(self, *, symbol=None, cycle_id=None, detail="",
                                 timestamp=None):
        return [self._emit(AlertType.OBSERVATION_CYCLE_FAILED, AlertSeverity.HIGH,
                           "Observation cycle failed", str(detail) or "CYCLE_FAILED",
                           symbol=symbol, timestamp=timestamp,
                           context={"cycle_id": cycle_id, "detail": str(detail)},
                           source="observation_driver")]

    def data_stale(self, *, symbol=None, reasons=(), timestamp=None):
        codes = [str(reason) for reason in reasons]
        return [self._emit(AlertType.DATA_STALE, AlertSeverity.HIGH, "Market data stale",
                           ", ".join(codes) or "DATA_STALE", symbol=symbol,
                           timestamp=timestamp, context={"reasons": codes},
                           source="observation_driver")]

    def learning_model_failure(self, *, detail="", model_id=None, timestamp=None):
        """Distinct from `model_failure`: that one is Phase 12 inference (MODEL_ERROR)."""
        return [self._emit(AlertType.MODEL_FAILURE, AlertSeverity.HIGH, "Model failure",
                           str(detail) or "MODEL_FAILURE", symbol=None, timestamp=timestamp,
                           context={"model_id": model_id, "detail": str(detail)},
                           source="ai_learning")]

    def labeling_failure(self, *, observation_id=None, detail="", timestamp=None):
        return [self._emit(AlertType.LABELING_FAILURE, AlertSeverity.MEDIUM,
                           "Labeling failure", str(detail) or "LABELING_FAILURE",
                           symbol=None, timestamp=timestamp,
                           context={"observation_id": observation_id,
                                    "detail": str(detail)}, source="observation_driver")]

    def dataset_failure(self, *, observation_id=None, detail="", timestamp=None):
        return [self._emit(AlertType.DATASET_FAILURE, AlertSeverity.MEDIUM,
                           "Dataset failure", str(detail) or "DATASET_FAILURE",
                           symbol=None, timestamp=timestamp,
                           context={"observation_id": observation_id,
                                    "detail": str(detail)}, source="dataset_pipeline")]

    def model_drift(self, *, report=None, model_id=None, timestamp=None):
        """FLAG_ONLY: an alert is the entire response to drift."""
        payload = report.as_dict() if hasattr(report, "as_dict") else (report or {})
        signals = payload.get("signals") or []
        kinds = [str(signal.get("kind")) for signal in signals
                 if isinstance(signal, dict) and signal.get("flagged")]
        return [self._emit(AlertType.MODEL_DRIFT, AlertSeverity.MEDIUM, "Model drift",
                           ", ".join(kinds) or "DRIFT_FLAGGED", symbol=None,
                           timestamp=timestamp,
                           context={"model_id": model_id, "kinds": kinds,
                                    "action": "FLAG_ONLY"}, source="ai_learning")]

    def performance_degradation(self, *, window="", metric="", baseline=None, current=None,
                                timestamp=None):
        return [self._emit(AlertType.PERFORMANCE_DEGRADATION, AlertSeverity.HIGH,
                           "Performance degradation",
                           f"{metric} {baseline} -> {current} over {window}", symbol=None,
                           timestamp=timestamp,
                           context={"window": window, "metric": metric,
                                    "baseline": baseline, "current": current},
                           source="ai_learning")]

    def high_confidence_failure(self, *, analysis=None, timestamp=None):
        payload = analysis.as_dict() if hasattr(analysis, "as_dict") else (analysis or {})
        return [self._emit(AlertType.HIGH_CONFIDENCE_FAILURE, AlertSeverity.HIGH,
                           "High confidence failure",
                           f"predicted {payload.get('predicted')} at "
                           f"{payload.get('confidence')}, actual {payload.get('actual')}",
                           symbol=None, timestamp=timestamp, context=payload,
                           source="ai_learning")]

    def edge_status(self, *, report=None, timestamp=None, symbol=None):
        """One method for the three edge alert types; the verdict picks which."""
        payload = report.as_dict() if hasattr(report, "as_dict") else (report or {})
        verdict = str(payload.get("verdict") or "NO_EDGE")
        mapping = {"EDGE_DETECTED": (AlertType.EDGE_DETECTED, AlertSeverity.MEDIUM),
                   "INSUFFICIENT_DATA": (AlertType.INSUFFICIENT_DATA, AlertSeverity.LOW),
                   "UNSTABLE_EDGE": (AlertType.NO_EDGE, AlertSeverity.MEDIUM),
                   "NO_EDGE": (AlertType.NO_EDGE, AlertSeverity.LOW)}
        alert_type, severity = mapping.get(verdict, (AlertType.NO_EDGE, AlertSeverity.LOW))
        reasons = [str(reason) for reason in payload.get("reasons", [])]
        return [self._emit(alert_type, severity, "Edge evaluation",
                           ", ".join([verdict, *reasons]), symbol=symbol,
                           timestamp=timestamp,
                           context={"verdict": verdict, "reasons": reasons,
                                    "samples": payload.get("samples"),
                                    "evidence": payload.get("evidence")},
                           source="edge_detector")]
