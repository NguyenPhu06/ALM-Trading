"""The circuit breaker (section 22).

Eleven conditions disable DEMO execution automatically. Tripping blocks NEW
orders and nothing else — open positions are left alone, exactly as with the kill
switch, because liquidating them would be a second and larger decision taken by
code that has just discovered it cannot trust its inputs.
"""
import pytest

from database.models import CircuitBreakerEventRecord
from database.repositories.validation import ValidationRepository
from execution.mt5.kill_switch import ExecutionKillSwitch
from validation.circuit_breaker import (
    CIRCUIT_BREAKER_OPEN, POSITIONS_UNTOUCHED, BreakerSignals, BreakerState, BreakerTrigger,
    CircuitBreaker,
)
from tests.phase16_helpers import DEMO_SERVER, armed, live_context, order, service_for, settings
from tests.phase17_helpers import breaker


def signals(**overrides):
    return BreakerSignals(**overrides)


# --------------------------------------------------------------- the triggers
def test_all_eleven_declared_triggers_exist():
    assert {str(trigger) for trigger in BreakerTrigger} == {
        "DAILY_LOSS_EXCEEDED", "DRAWDOWN_EXCEEDED", "RECONCILIATION_FAILURE",
        "REPEATED_EXECUTION_FAILURES", "STALE_MARKET_DATA", "MODEL_FAILURE",
        "RISK_ENGINE_FAILURE", "UNEXPECTED_ACCOUNT", "UNEXPECTED_BROKER",
        "UNEXPECTED_SYMBOL", "ABNORMAL_SPREAD"}


@pytest.mark.parametrize("kwargs,trigger", [
    (dict(daily_drawdown=0.50), BreakerTrigger.DAILY_LOSS_EXCEEDED),
    (dict(total_drawdown=0.50), BreakerTrigger.DRAWDOWN_EXCEEDED),
    (dict(reconciliation_failures=1), BreakerTrigger.RECONCILIATION_FAILURE),
    (dict(execution_failures=5), BreakerTrigger.REPEATED_EXECUTION_FAILURES),
    (dict(data_age_seconds=10_000.0), BreakerTrigger.STALE_MARKET_DATA),
    (dict(model_failed=True), BreakerTrigger.MODEL_FAILURE),
    (dict(risk_engine_failed=True), BreakerTrigger.RISK_ENGINE_FAILURE),
    (dict(account_type="REAL"), BreakerTrigger.UNEXPECTED_ACCOUNT),
    (dict(broker="Other", expected_broker="Exness"), BreakerTrigger.UNEXPECTED_BROKER),
    (dict(symbol="XAUUSD", allowed_symbols=("EURUSD",)), BreakerTrigger.UNEXPECTED_SYMBOL),
    (dict(spread=0.10), BreakerTrigger.ABNORMAL_SPREAD),
])
def test_each_condition_fires_its_trigger(kwargs, trigger):
    assert trigger in breaker().evaluate(signals(**kwargs))


def test_a_healthy_system_fires_nothing():
    assert breaker().evaluate(signals()) == ()


def test_a_demo_account_is_not_an_unexpected_account():
    assert breaker().evaluate(signals(account_type="DEMO")) == ()
    assert breaker().evaluate(signals(account_type="CONTEST")) == ()


def test_an_allowed_symbol_is_not_unexpected():
    assert breaker().evaluate(
        signals(symbol="EURUSD", allowed_symbols=("EURUSD", "GBPUSD"))) == ()


def test_a_merely_wide_spread_is_not_abnormal():
    """Wide is a gate refusal; abnormal is a breaker trip. They are different."""
    from execution.demo.limits import DemoRiskLimits

    limits = DemoRiskLimits.from_config()
    wide = limits.max_spread * 1.5
    assert breaker().evaluate(signals(spread=wide)) == ()
    assert BreakerTrigger.ABNORMAL_SPREAD in breaker().evaluate(
        signals(spread=limits.max_spread * 3))


def test_unknown_signals_fire_nothing():
    """None means not observed, which is not the same as bad."""
    assert breaker().evaluate(signals(daily_drawdown=None, spread=None,
                                      data_age_seconds=None)) == ()


def test_evaluating_never_trips_the_breaker():
    live = breaker()
    live.evaluate(signals(daily_drawdown=0.50))
    assert live.state is BreakerState.CLOSED


# ------------------------------------------------------------------ the trip
def test_tripping_opens_the_breaker():
    live = breaker()
    live.check(signals(daily_drawdown=0.50))
    assert live.open is True and live.state is BreakerState.OPEN
    assert BreakerTrigger.DAILY_LOSS_EXCEEDED in live.triggers


def test_tripping_engages_the_kill_switch():
    switch = ExecutionKillSwitch(engaged=False, reason="TEST")
    live = breaker(kill_switch=switch)
    live.check(signals(model_failed=True))
    assert switch.engaged is True


def test_tripping_never_closes_open_positions():
    live = breaker()
    event = live.check(signals(daily_drawdown=0.50))
    assert event.positions_closed is False
    assert event.as_dict()["positions"] == POSITIONS_UNTOUCHED


def test_an_open_breaker_blocks():
    live = breaker()
    live.check(signals(daily_drawdown=0.50))
    assert live.permits() is False
    assert CIRCUIT_BREAKER_OPEN in live.blocking_reasons()


def test_a_closed_breaker_blocks_nothing():
    live = breaker()
    assert live.permits() is True and live.blocking_reasons() == ()


def test_the_breaker_never_closes_itself():
    """No timeout, no retry counter, no automatic reset."""
    live = breaker()
    live.check(signals(daily_drawdown=0.50))
    for _ in range(5):
        live.check(signals())
    assert live.open is True
    assert live.status()["auto_reset"] is False


def test_a_disabled_breaker_does_not_trip():
    live = CircuitBreaker(settings(circuit_breaker_enabled=False))
    assert live.check(signals(daily_drawdown=0.50)) is None
    assert live.open is False


def test_disabling_the_breaker_does_not_enable_execution():
    """It removes an automatic reason to stop; it opens nothing."""
    config = settings(circuit_breaker_enabled=False)
    assert config.execution_mode == "OBSERVATION"
    assert config.demo_trading_enabled is False


# ---------------------------------------------------------- blocking execution
def test_an_open_breaker_blocks_a_demo_order(db_session):
    service, fake = service_for(db_session)
    service.breaker.check(signals(daily_drawdown=0.50))

    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert not outcome.executed
    assert fake.sent == []


def test_the_breaker_blocks_even_after_the_kill_switch_is_released(db_session):
    """The reason it is a separate mechanism: recovery cannot be one button press."""
    service, fake = service_for(db_session)
    service.breaker.check(signals(daily_drawdown=0.50))
    service.release_kill_switch("operator released the switch")

    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert not outcome.executed and fake.sent == []
    assert CIRCUIT_BREAKER_OPEN in outcome.reasons


def test_an_open_breaker_is_on_the_status_payload(db_session):
    service, _ = service_for(db_session)
    service.breaker.check(signals(daily_drawdown=0.50))
    status = service.status()
    assert status["circuit_breaker"]["open"] is True
    assert CIRCUIT_BREAKER_OPEN in status["blocked_by"]


def test_an_open_breaker_does_not_close_a_position(db_session):
    service, fake = service_for(db_session)
    request = order()
    outcome = service.submit(request, live_context(service, request))
    ticket = outcome.result.broker_ticket

    service.breaker.check(signals(daily_drawdown=0.50))
    assert service.client.get_position(ticket) is not None
    assert len(fake.sent) == 1, "no closing order may be sent"


# ---------------------------------------------------------------- persistence
def test_a_trip_persists(db_session):
    repository = ValidationRepository(db_session)
    live = breaker(repository=repository)
    live.check(signals(daily_drawdown=0.50))
    row = db_session.query(CircuitBreakerEventRecord).one()
    assert row.state == "OPEN" and row.positions_closed is False
    assert "DAILY_LOSS_EXCEEDED" in row.triggers


def test_a_trip_raises_a_critical_alert(db_session):
    from database.models import DashboardAlertRecord
    from database.repositories import AlertRepository
    from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter

    router = AlertRouter(AlertEngine(AlertRepositoryNotificationProvider(
        AlertRepository(db_session))))
    breaker(alerts=router).check(signals(daily_drawdown=0.50))
    rows = db_session.query(DashboardAlertRecord).all()
    assert any(row.alert_type == "CIRCUIT_BREAKER_TRIPPED" and row.severity == "CRITICAL"
               for row in rows)
