from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4
class AlertType(StrEnum):
    LIQUIDITY_SWEEP="LIQUIDITY_SWEEP";BOS="BOS";CHOCH="CHOCH";MTF_CONFLICT="MTF_CONFLICT";STRATEGY_READY="STRATEGY_READY";STRATEGY_INVALIDATED="STRATEGY_INVALIDATED";DCA_TRIGGER="DCA_TRIGGER";DCA_BLOCKED="DCA_BLOCKED";EXIT_TRIGGER="EXIT_TRIGGER";RISK_WARNING="RISK_WARNING";RISK_BLOCK="RISK_BLOCK";MODEL_ERROR="MODEL_ERROR";DATA_ERROR="DATA_ERROR";PROVIDER_ERROR="PROVIDER_ERROR"
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
class AlertEngine:
    def __init__(self,provider=None):self.provider=provider or DashboardNotificationProvider()
    def emit(self,alert_type,severity,title,message,*,symbol=None,source="backend",timestamp=None,context=None):
        alert=Alert(uuid4().hex,timestamp or datetime.now(timezone.utc),symbol,AlertType(alert_type),AlertSeverity(severity),title,message,source,context=context);self.provider.notify(alert);return alert
    def list(self,*,symbol=None,alert_type=None,severity=None,unread=None):
        rows=list(getattr(self.provider,"alerts",[]))
        if symbol:rows=[a for a in rows if a.symbol==symbol]
        if alert_type:rows=[a for a in rows if a.alert_type.value==alert_type]
        if severity:rows=[a for a in rows if a.severity.value==severity]
        if unread is not None:rows=[a for a in rows if a.read is not unread]
        return sorted(rows,key=lambda a:a.timestamp,reverse=True)
