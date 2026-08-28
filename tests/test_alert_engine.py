from monitoring.alerts import AlertEngine,AlertSeverity,AlertType,DashboardNotificationProvider
def test_alert_engine_emits_filters_and_dashboard_only_notification():
    provider=DashboardNotificationProvider();engine=AlertEngine(provider);engine.emit(AlertType.MTF_CONFLICT,AlertSeverity.HIGH,"Conflict","Wait",symbol="EURUSD")
    assert engine.list(symbol="EURUSD",severity="HIGH")[0].message=="Wait" and not hasattr(provider,"credentials")


# ---------------------------------------------- Phase 16: the section 27 alerts
# Every execution decision reaches the alert store. Alerting is a side channel:
# none of these methods can change what the execution path decided.
from database.models import DashboardAlertRecord
from monitoring.alerts import AlertType
from tests import phase16_helpers as p16

PHASE_16_ALERT_TYPES = {
    "DEMO_EXECUTION_ENABLED", "REAL_ACCOUNT_BLOCKED", "ORDER_SUBMITTED", "ORDER_FILLED",
    "ORDER_REJECTED", "ORDER_BLOCKED", "RISK_LIMIT_REACHED", "DAILY_LOSS_LIMIT",
    "DRAWDOWN_LIMIT", "SPREAD_LIMIT", "SLIPPAGE_LIMIT", "RECONCILIATION_FAILURE",
    "MT5_DISCONNECTED", "KILL_SWITCH_ACTIVE", "EXECUTION_DISABLED", "MODEL_FAILURE",
}


def alert_types(db_session):
    return {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}


def test_every_declared_phase_16_alert_type_exists():
    """Section 27, name for name."""
    declared = {str(alert) for alert in AlertType}
    assert PHASE_16_ALERT_TYPES <= declared


def test_arming_demo_execution_raises_a_critical_alert(db_session):
    service, _ = p16.service_for(db_session)
    request = p16.order()
    service.submit(request, p16.live_context(service, request))
    rows = [row for row in db_session.query(DashboardAlertRecord).all()
            if row.alert_type == "DEMO_EXECUTION_ENABLED"]
    assert rows and rows[0].severity == "CRITICAL"
    assert rows[0].context_json["live_trading_enabled"] is False


def test_arming_is_announced_once_not_once_per_order(db_session):
    service, _ = p16.service_for(db_session)
    for index in range(3):
        request = p16.order(signal_id=f"signal-{index}")
        service.submit(request, p16.live_context(service, request))
    rows = [row for row in db_session.query(DashboardAlertRecord).all()
            if row.alert_type == "DEMO_EXECUTION_ENABLED"]
    assert len(rows) == 1


def test_a_fill_raises_submitted_and_filled(db_session):
    service, _ = p16.service_for(db_session)
    request = p16.order()
    service.submit(request, p16.live_context(service, request))
    assert {"ORDER_SUBMITTED", "ORDER_FILLED"} <= alert_types(db_session)


def test_a_blocked_order_raises_order_blocked(db_session):
    service, _ = p16.service_for(db_session)
    request = p16.order()
    service.submit(request, p16.live_context(service, request, risk_allowed=False))
    assert "ORDER_BLOCKED" in alert_types(db_session)


def test_a_breached_daily_loss_raises_its_own_alert(db_session):
    from execution.demo.limits import MAX_DAILY_LOSS

    service, _ = p16.service_for(db_session)
    request = p16.order()
    breached = p16.daily_state(daily_drawdown=0.9, blocked=True, reasons=(MAX_DAILY_LOSS,))
    service.submit(request, p16.live_context(service, request, daily=breached))
    assert "DAILY_LOSS_LIMIT" in alert_types(db_session)


def test_a_wide_spread_raises_its_own_alert(db_session):
    service, _ = p16.service_for(db_session)
    request = p16.order()
    service.submit(request, p16.live_context(service, request,
                                             quote={"bid": 1.1000, "ask": 1.1100}))
    assert "SPREAD_LIMIT" in alert_types(db_session)


def test_a_non_broker_mode_raises_execution_disabled(db_session):
    service, _ = p16.service_for(db_session, p16.settings())
    request = p16.order()
    service.submit(request, p16.live_context(service, request))
    assert "EXECUTION_DISABLED" in alert_types(db_session)


def test_manual_mode_asks_for_an_approval(db_session):
    service, _ = p16.service_for(db_session, p16.manual())
    request = p16.order()
    service.submit(request, p16.live_context(service, request))
    assert "MANUAL_APPROVAL_REQUIRED" in alert_types(db_session)


def test_alerting_cannot_change_a_decision(db_session):
    """A failing alert router must not turn a refusal into a fill, or vice versa."""
    class Exploding:
        def __getattr__(self, name):
            def handler(**kwargs):
                raise RuntimeError("alerting is down")
            return handler

    service, fake = p16.service_for(db_session, with_alerts=False)
    service.alerts = Exploding()
    request = p16.order()
    outcome = service.submit(request, p16.live_context(service, request))
    assert outcome.executed and len(fake.sent) == 1
