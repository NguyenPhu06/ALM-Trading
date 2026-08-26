from dataclasses import asdict
from sqlalchemy import desc
from database.models import DashboardAlertRecord
class AlertRepository:
    def __init__(self,session):self.session=session
    def add(self,a):
        row=DashboardAlertRecord(alert_id=a.alert_id,timestamp=a.timestamp,symbol=a.symbol,alert_type=a.alert_type.value,severity=a.severity.value,title=a.title,message=a.message,source=a.source,version=a.version,data_quality=a.data_quality,read=a.read,context_json=a.context);self.session.add(row);self.session.commit();return row
    def list(self,*,symbol=None,alert_type=None,severity=None,unread=None,limit=100):
        q=self.session.query(DashboardAlertRecord)
        if symbol:q=q.filter(DashboardAlertRecord.symbol==symbol)
        if alert_type:q=q.filter(DashboardAlertRecord.alert_type==alert_type)
        if severity:q=q.filter(DashboardAlertRecord.severity==severity)
        if unread is not None:q=q.filter(DashboardAlertRecord.read.is_(not unread))
        return q.order_by(desc(DashboardAlertRecord.timestamp)).limit(limit).all()
