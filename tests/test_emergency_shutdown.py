"""Emergency protection (section 17).

Eleven conditions shut execution down. "Shut down" means the kill switch is
engaged and no NEW order may be sent — and, deliberately, nothing else. Open
positions are left alone, because liquidation is a second and larger decision
taken by code that has just discovered it cannot trust its inputs.
"""
import pytest

from database.models import DemoEmergencyEventRecord, KillSwitchEventRecord
from database.repositories.demo import DemoTradingRepository
from database.repositories.execution import ExecutionRepository
from execution.demo.emergency import (
    EmergencyController, EmergencySignals, EmergencyTrigger, POSITIONS_UNTOUCHED,
    SHUTDOWN_ACTION,
)
from execution.demo.limits import DemoRiskLimits
from execution.mt5.kill_switch import ExecutionKillSwitch
from execution.mt5.mock import FakeExecutionModule
from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter
from database.repositories import AlertRepository
from tests.phase16_helpers import DEMO_SERVER, armed, live_context, order, service_for

LIMITS = DemoRiskLimits(max_daily_loss=0.02, max_total_drawdown=0.05, max_spread=0.0005)


def controller(**kwargs):
    kwargs.setdefault("limits", LIMITS)
    kwargs.setdefault("kill_switch", ExecutionKillSwitch(engaged=False, reason="TEST"))
    return EmergencyController(armed(), **kwargs)


def signals(**overrides):
    return EmergencySignals(**overrides)


# ------------------------------------------------------------- the conditions
@pytest.mark.parametrize("kwargs,trigger", [
    (dict(daily_drawdown=0.05), EmergencyTrigger.DAILY_LOSS_LIMIT),
    (dict(total_drawdown=0.10), EmergencyTrigger.DRAWDOWN_LIMIT),
    (dict(execution_errors=5), EmergencyTrigger.EXECUTION_ERRORS),
    (dict(connected=False), EmergencyTrigger.MT5_CONNECTION_UNSTABLE),
    (dict(connection_failures=9), EmergencyTrigger.MT5_CONNECTION_UNSTABLE),
    (dict(data_age_seconds=10_000.0), EmergencyTrigger.DATA_STALE),
    (dict(reconciliation_failures=1), EmergencyTrigger.RECONCILIATION_FAILURE),
    (dict(account_type="REAL"), EmergencyTrigger.UNEXPECTED_ACCOUNT_TYPE),
    (dict(broker="Other", expected_broker="Exness"), EmergencyTrigger.UNEXPECTED_BROKER),
    (dict(server="Other-Live", expected_server=DEMO_SERVER), EmergencyTrigger.UNEXPECTED_BROKER),
    (dict(spread=0.01), EmergencyTrigger.SPREAD_LIMIT),
    (dict(model_failed=True), EmergencyTrigger.MODEL_FAILURE),
    (dict(risk_engine_failed=True), EmergencyTrigger.RISK_ENGINE_FAILURE),
])
def test_each_condition_triggers_a_shutdown(kwargs, trigger):
    decision = controller().evaluate(signals(**kwargs))
    assert decision.shutdown and trigger in decision.triggers


def test_a_healthy_system_does_not_shut_down():
    decision = controller().evaluate(signals())
    assert not decision.shutdown and decision.triggers == ()


def test_a_demo_account_type_is_not_a_trigger():
    assert not controller().evaluate(signals(account_type="DEMO")).shutdown
    assert not controller().evaluate(signals(account_type="CONTEST")).shutdown


def test_unknown_signals_trigger_nothing():
    """None means "not observed", which is not the same as "bad"."""
    decision = controller().evaluate(signals(daily_drawdown=None, total_drawdown=None,
                                             data_age_seconds=None, spread=None))
    assert not decision.shutdown


def test_several_conditions_are_all_reported():
    decision = controller().evaluate(signals(daily_drawdown=0.05, model_failed=True))
    assert {EmergencyTrigger.DAILY_LOSS_LIMIT, EmergencyTrigger.MODEL_FAILURE} <= set(
        decision.triggers)


# --------------------------------------------------------------- the shutdown
def test_a_shutdown_engages_the_kill_switch():
    switch = ExecutionKillSwitch(engaged=False, reason="TEST")
    controller(kill_switch=switch).check(signals(daily_drawdown=0.05))
    assert switch.engaged
    assert switch.last_event.actor == "emergency"


def test_a_shutdown_never_closes_open_positions():
    decision = controller().check(signals(daily_drawdown=0.05))
    assert decision.positions_closed is False
    assert decision.as_dict()["positions"] == POSITIONS_UNTOUCHED
    assert decision.action == SHUTDOWN_ACTION


def test_the_switch_never_releases_itself():
    switch = ExecutionKillSwitch(engaged=False, reason="TEST")
    live = controller(kill_switch=switch)
    live.check(signals(daily_drawdown=0.05))
    live.check(signals())
    assert switch.engaged, "recovery is an operator action, never automatic"


def test_a_healthy_check_does_not_touch_the_switch():
    switch = ExecutionKillSwitch(engaged=False, reason="TEST")
    controller(kill_switch=switch).check(signals())
    assert not switch.engaged


def test_the_shutdown_is_persisted(db_session):
    live = controller(repository=DemoTradingRepository(db_session))
    live.check(signals(daily_drawdown=0.05))
    row = db_session.query(DemoEmergencyEventRecord).one()
    assert row.shutdown is True and row.positions_closed is False
    assert "DAILY_LOSS_LIMIT" in row.triggers


def test_the_shutdown_raises_a_critical_alert(db_session):
    from database.models import DashboardAlertRecord

    router = AlertRouter(AlertEngine(AlertRepositoryNotificationProvider(
        AlertRepository(db_session))))
    controller(alerts=router).check(signals(daily_drawdown=0.05))
    rows = db_session.query(DashboardAlertRecord).all()
    assert any(row.alert_type == "EMERGENCY_SHUTDOWN" and row.severity == "CRITICAL"
               for row in rows)


def test_the_kill_switch_event_is_persisted(db_session):
    live = controller(repository=ExecutionRepository(db_session))
    live.check(signals(total_drawdown=0.10))
    row = db_session.query(KillSwitchEventRecord).one()
    assert row.engaged is True and row.actor == "emergency"


# ---------------------------------------------------------------- end to end
def test_a_reconciliation_failure_shuts_execution_down(db_session):
    """Section 15 plus section 17: a mismatch is a safe shutdown, not a warning."""
    service, fake = service_for(db_session)
    request = order()
    # The broker reports a fill the position store never shows.
    fake.fill_volume = 0.01
    fake.retcode = 10010
    outcome = service.submit(request, live_context(service, request))

    assert outcome.reconciliation is not None and not outcome.reconciliation.matched
    assert service.kill_switch.engaged, "a reconciliation failure blocks new orders"


def test_after_an_emergency_the_next_order_is_blocked(db_session):
    service, fake = service_for(db_session)
    service.check_emergency(daily_drawdown=0.99)
    assert service.kill_switch.engaged

    request = order(signal_id="signal-002")
    outcome = service.submit(request, live_context(service, request))
    assert not outcome.approved
    assert "KILL_SWITCH_ENGAGED" in outcome.reasons
    assert fake.sent == []


def test_an_unexpected_account_type_shuts_execution_down(db_session):
    service, _ = service_for(db_session, module=FakeExecutionModule(
        trade_mode=2, server=DEMO_SERVER))
    decision = service.check_emergency()
    assert decision.shutdown
    assert EmergencyTrigger.UNEXPECTED_ACCOUNT_TYPE in decision.triggers
    assert service.kill_switch.engaged
