from monitoring.alerts import AlertEngine,AlertSeverity,AlertType,DashboardNotificationProvider
def test_alert_engine_emits_filters_and_dashboard_only_notification():
    provider=DashboardNotificationProvider();engine=AlertEngine(provider);engine.emit(AlertType.MTF_CONFLICT,AlertSeverity.HIGH,"Conflict","Wait",symbol="EURUSD")
    assert engine.list(symbol="EURUSD",severity="HIGH")[0].message=="Wait" and not hasattr(provider,"credentials")
