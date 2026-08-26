from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4
class AlertType(StrEnum):
    LIQUIDITY_SWEEP="LIQUIDITY_SWEEP";BOS="BOS";CHOCH="CHOCH";MTF_CONFLICT="MTF_CONFLICT";STRATEGY_READY="STRATEGY_READY";STRATEGY_INVALIDATED="STRATEGY_INVALIDATED";DCA_TRIGGER="DCA_TRIGGER";DCA_BLOCKED="DCA_BLOCKED";EXIT_TRIGGER="EXIT_TRIGGER";RISK_WARNING="RISK_WARNING";RISK_BLOCK="RISK_BLOCK";MODEL_ERROR="MODEL_ERROR";DATA_ERROR="DATA_ERROR";PROVIDER_ERROR="PROVIDER_ERROR";PAPER_ENTRY="PAPER_ENTRY";EXECUTION_ENABLED="EXECUTION_ENABLED";EXECUTION_BLOCKED="EXECUTION_BLOCKED";ORDER_SUBMITTED="ORDER_SUBMITTED";ORDER_FILLED="ORDER_FILLED";ORDER_REJECTED="ORDER_REJECTED";RECONCILIATION_FAILED="RECONCILIATION_FAILED";KILL_SWITCH_TRIGGERED="KILL_SWITCH_TRIGGERED"
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
