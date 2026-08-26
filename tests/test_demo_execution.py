"""The manual DEMO execution endpoint and service pipeline."""
import pytest

from database.models import (
    DashboardAlertRecord,
    ExecutionRequestRecord,
    ExecutionResultRecord,
    ReconciliationRecordRow,
)
from execution.mt5.mock import FakeExecutionModule
from execution.mt5.order_request import ExecutionIntent, OrderSide
from execution.mt5.order_result import ExecutionStatus, RejectionReason
from tests.phase11_helpers import DEMO_SERVER, armed, order, service_for, settings


# ------------------------------------------------------------------- service
def test_an_armed_demo_configuration_executes_and_reconciles(db_session):
    service, fake = service_for(db_session)
    outcome = service.execute(order())

    assert outcome.decision.approved and outcome.executed
    assert outcome.result.status is ExecutionStatus.FILLED
    assert outcome.result.broker_ticket == 700001
    assert outcome.result.filled_volume == 0.01
    assert outcome.result.filled_price == pytest.approx(1.10024)
    assert outcome.reconciliation.matched
    assert outcome.position is not None and outcome.position.ticket == 700001


def test_the_broker_symbol_is_used_on_the_wire_but_canonical_in_our_records(db_session):
    service, fake = service_for(db_session)
    outcome = service.execute(order(symbol="EURUSD"))
    assert fake.sent[0]["symbol"] == "EURUSDm"
    assert outcome.result.symbol == "EURUSD"


def test_a_broker_rejection_is_recorded_without_a_ticket(db_session):
    service, fake = service_for(db_session, module=FakeExecutionModule(
        retcode=10019, server=DEMO_SERVER))
    outcome = service.execute(order())
    assert outcome.decision.approved, "the guard approved; the broker refused"
    assert not outcome.executed
    assert outcome.result.status is ExecutionStatus.REJECTED
    assert outcome.result.error_code == "MT5_RETCODE_10019"
    assert outcome.result.broker_ticket is None


def test_a_transport_failure_is_recorded_as_failed(db_session):
    service, _ = service_for(db_session, module=FakeExecutionModule(
        raise_on_send=True, server=DEMO_SERVER))
    outcome = service.execute(order())
    assert outcome.result.status is ExecutionStatus.FAILED
    assert outcome.result.error_code == "ORDER_SEND_EXCEPTION"


def test_a_partial_fill_is_reported_as_partial(db_session):
    service, _ = service_for(db_session, module=FakeExecutionModule(
        retcode=10010, fill_volume=0.005, server=DEMO_SERVER))
    outcome = service.execute(order(volume=0.01))
    assert outcome.result.status is ExecutionStatus.PARTIAL
    assert outcome.result.filled_volume == 0.005


def test_every_execution_persists_request_result_and_reconciliation(db_session):
    service, _ = service_for(db_session)
    service.execute(order())
    assert db_session.query(ExecutionRequestRecord).count() == 1
    assert db_session.query(ExecutionResultRecord).count() == 1
    assert db_session.query(ReconciliationRecordRow).count() == 1


def test_a_refused_request_is_persisted_too(db_session):
    """A refusal must be as auditable as a fill."""
    service, _ = service_for(db_session, settings())
    service.execute(order())
    assert db_session.query(ExecutionRequestRecord).count() == 1
    result = db_session.query(ExecutionResultRecord).one()
    assert result.status == "BLOCKED" and result.broker_ticket is None


def test_execution_raises_alerts(db_session):
    service, _ = service_for(db_session)
    service.execute(order())
    types = {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}
    assert {"ORDER_SUBMITTED", "ORDER_FILLED"} <= types


def test_a_rejection_raises_an_order_rejected_alert(db_session):
    service, _ = service_for(db_session, settings())
    service.execute(order())
    rows = db_session.query(DashboardAlertRecord).all()
    assert any(row.alert_type == "ORDER_REJECTED" for row in rows)


def test_a_real_account_rejection_is_critical(db_session):
    from tests.phase11_helpers import REAL_TRADE_MODE

    service, _ = service_for(db_session, module=FakeExecutionModule(
        trade_mode=REAL_TRADE_MODE, server=DEMO_SERVER))
    service.execute(order())
    rows = [row for row in db_session.query(DashboardAlertRecord).all()
            if row.alert_type == "ORDER_REJECTED"]
    assert rows and rows[0].severity == "CRITICAL"


# ------------------------------------------------------------------ endpoint
def test_the_endpoint_refuses_under_the_shipped_defaults(client):
    response = client.post("/execution/demo/test",
                           json={"symbol": "EURUSD", "side": "BUY", "volume": 0.01})
    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False and body["executed"] is False
    assert body["automated_trading"] is False
    assert body["environment"] == "DEMO"
    reasons = body["result"]["reasons"]
    assert "DEMO_TRADING_DISABLED" in reasons and "KILL_SWITCH_ENGAGED" in reasons


def test_the_endpoint_validates_the_side(client):
    response = client.post("/execution/demo/test",
                           json={"symbol": "EURUSD", "side": "SIDEWAYS", "volume": 0.01})
    assert response.status_code == 422


def test_the_endpoint_rejects_a_non_positive_volume(client):
    response = client.post("/execution/demo/test",
                           json={"symbol": "EURUSD", "side": "BUY", "volume": 0})
    assert response.status_code == 422


def test_the_endpoint_audits_even_a_refused_request(client, db_session):
    from database.models import ExecutionAuditLogRecord

    client.post("/execution/demo/test", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.01})
    stages = [row.stage for row in db_session.query(ExecutionAuditLogRecord).all()]
    assert "REQUEST" in stages and "VALIDATION" in stages and "RESULT" in stages


def test_the_status_endpoint_reports_blocked_by_default(client):
    body = client.get("/execution/status").json()["data"]
    assert body["execution_state"] == "EXECUTION_BLOCKED"
    assert body["execution_mode"] == "MANUAL_DEMO_TEST"
    assert body["automated_trading"] is False
    assert set(body["blocked_by"]) >= {"DEMO_TRADING_DISABLED", "MT5_EXECUTION_DISABLED",
                                       "KILL_SWITCH_ENGAGED"}


def test_the_kill_switch_endpoints_engage_and_release(client):
    engaged = client.post("/execution/kill-switch/engage", json={"reason": "api test"}).json()
    assert engaged["engaged"] is True and engaged["execution"] == "EXECUTION_BLOCKED"
    released = client.post("/execution/kill-switch/release",
                           json={"reason": "verified demo account"}).json()
    assert released["engaged"] is False and released["execution"] == "EXECUTION_ENABLED"
    client.post("/execution/kill-switch/engage", json={"reason": "restore default"})


def test_releasing_the_kill_switch_requires_a_reason(client):
    response = client.post("/execution/kill-switch/release", json={"reason": "x"})
    assert response.status_code == 422
