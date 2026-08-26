"""Alerts must have exactly one store.

Phase 9 shipped an AlertEngine writing to an in-memory provider and a
/dashboard/alerts endpoint reading from PostgreSQL, so nothing emitted was ever
visible. These tests pin emission and read-back to the same database rows.
"""
from types import SimpleNamespace

import pytest

from database.models import DashboardAlertRecord
from database.repositories import AlertRepository
from monitoring.alerts import (
    AlertEngine,
    AlertRepositoryNotificationProvider,
    AlertRouter,
    AlertSeverity,
    AlertType,
)
from paper import PaperExecutionResult


def engine_for(db_session):
    return AlertEngine(AlertRepositoryNotificationProvider(AlertRepository(db_session)))


def test_emitted_alert_is_persisted_and_read_back_through_the_same_store(db_session):
    engine = engine_for(db_session)
    engine.emit(AlertType.RISK_BLOCK, AlertSeverity.CRITICAL, "Kill switch", "GLOBAL_KILL_SWITCH_ACTIVATED",
                symbol="EURUSD")
    assert db_session.query(DashboardAlertRecord).count() == 1
    rows = engine.list(symbol="EURUSD")
    assert len(rows) == 1 and rows[0].message == "GLOBAL_KILL_SWITCH_ACTIVATED"
    assert rows[0].alert_type == "RISK_BLOCK" and rows[0].severity == "CRITICAL"


def test_engine_filters_delegate_to_the_repository(db_session):
    engine = engine_for(db_session)
    engine.emit(AlertType.DATA_ERROR, AlertSeverity.CRITICAL, "a", "a", symbol="EURUSD")
    engine.emit(AlertType.PROVIDER_ERROR, AlertSeverity.HIGH, "b", "b", symbol="GBPUSD")
    assert len(engine.list(symbol="EURUSD")) == 1
    assert len(engine.list(alert_type="PROVIDER_ERROR")) == 1
    assert len(engine.list(severity="CRITICAL")) == 1
    assert len(engine.list(unread=True)) == 2


def test_dashboard_alerts_endpoint_returns_emitted_alerts(client, db_session):
    engine_for(db_session).emit(AlertType.STRATEGY_INVALIDATED, AlertSeverity.HIGH,
                                "Strategy invalidated", "WHY_INVALIDATED:DATA_QUALITY_FAILURE",
                                symbol="EURUSD")
    body = client.get("/dashboard/alerts").json()
    assert body["data"]["unread"] == 1 and len(body["data"]["items"]) == 1
    assert body["data"]["items"][0]["message"] == "WHY_INVALIDATED:DATA_QUALITY_FAILURE"
    assert client.get("/dashboard/alerts?severity=HIGH").json()["data"]["items"]
    assert not client.get("/dashboard/alerts?severity=LOW").json()["data"]["items"]


def test_overview_unread_count_reflects_persisted_alerts(client, db_session):
    assert client.get("/dashboard/overview").json()["data"]["unread_alerts"] == 0
    engine_for(db_session).emit(AlertType.RISK_BLOCK, AlertSeverity.HIGH, "x", "y", symbol="EURUSD")
    assert client.get("/dashboard/overview").json()["data"]["unread_alerts"] == 1


@pytest.mark.parametrize(("reason", "expected_type", "expected_severity"), [
    ("GLOBAL_KILL_SWITCH", "RISK_BLOCK", "CRITICAL"),
    ("DATA_QUALITY_INVALID", "DATA_ERROR", "CRITICAL"),
    ("PROVIDER_UNAVAILABLE", "PROVIDER_ERROR", "HIGH"),
    ("MODEL_FAILURE", "MODEL_ERROR", "HIGH"),
    ("MAXIMUM_DAILY_LOSS", "RISK_BLOCK", "HIGH"),
])
def test_router_maps_entry_rejections_onto_the_existing_alert_contract(
    db_session, reason, expected_type, expected_severity,
):
    router = AlertRouter(engine_for(db_session))
    result = PaperExecutionResult(False, None, reason, 0., reason_codes=(f"WHY_REJECTED:{reason}",))
    router.execution_result(result, symbol="EURUSD", timestamp=None, action="ENTRY")
    row = db_session.query(DashboardAlertRecord).one()
    assert row.alert_type == expected_type and row.severity == expected_severity
    assert row.message == reason


def test_router_marks_risk_rejected_dca_as_dca_blocked(db_session):
    router = AlertRouter(engine_for(db_session))
    result = PaperExecutionResult(False, None, "MAXIMUM_DCA_ENTRIES", 0.)
    router.execution_result(result, symbol="EURUSD", timestamp=None, action="DCA")
    row = db_session.query(DashboardAlertRecord).one()
    assert row.alert_type == "DCA_BLOCKED" and row.context_json["action"] == "DCA"


def test_router_keeps_data_and_provider_types_for_dca_rejections(db_session):
    """A DCA blocked by bad data is a data error, not merely a DCA policy block."""
    router = AlertRouter(engine_for(db_session))
    router.execution_result(PaperExecutionResult(False, None, "DATA_QUALITY_INVALID", 0.),
                            symbol="EURUSD", timestamp=None, action="DCA")
    assert db_session.query(DashboardAlertRecord).one().alert_type == "DATA_ERROR"


def test_router_records_strategy_invalidation_and_executable_setups(db_session):
    router = AlertRouter(engine_for(db_session))
    router.strategy_decision(SimpleNamespace(
        timestamp=None, symbol="EURUSD", decision="INVALIDATE",
        reason_codes=("WHY_INVALIDATED", "MODEL_UNAVAILABLE")))
    router.strategy_decision(SimpleNamespace(
        timestamp=None, symbol="EURUSD", decision="SIMULATE", reason_codes=("WHY_READY",)))
    types = {r.alert_type for r in db_session.query(DashboardAlertRecord).all()}
    assert types == {"STRATEGY_INVALIDATED", "STRATEGY_READY"}


def test_router_records_timeframe_conflict_on_a_waiting_decision(db_session):
    router = AlertRouter(engine_for(db_session))
    router.strategy_decision(SimpleNamespace(
        timestamp=None, symbol="EURUSD", decision="WAIT",
        reason_codes=("WHY_WATCH", "TIMEFRAME_CONFLICT:M15")))
    assert db_session.query(DashboardAlertRecord).one().alert_type == "MTF_CONFLICT"


def test_router_records_paper_entry_dca_and_exit(db_session):
    router = AlertRouter(engine_for(db_session))
    order = SimpleNamespace(order_id="o1")
    router.execution_result(PaperExecutionResult(True, order, None, 1.), symbol="EURUSD",
                            timestamp=None, action="ENTRY")
    router.execution_result(PaperExecutionResult(True, order, None, 1.), symbol="EURUSD",
                            timestamp=None, action="DCA")
    router.paper_exit(SimpleNamespace(symbol="EURUSD", position_id="p1", realized_pnl=1.5,
                                      updated_at=None), reason_codes=("WHY_EXIT:TIME_CHECKPOINT",))
    types = {r.alert_type for r in db_session.query(DashboardAlertRecord).all()}
    assert types == {"PAPER_ENTRY", "DCA_TRIGGER", "EXIT_TRIGGER"}


def test_router_records_data_provider_and_kill_switch_events(db_session):
    router = AlertRouter(engine_for(db_session))
    router.data_quality_failure(symbol="EURUSD", detail="MISSING_CANDLES")
    router.provider_unavailable(provider="historical", status="OFFLINE")
    router.kill_switch(enabled=True)
    rows = {r.alert_type: r for r in db_session.query(DashboardAlertRecord).all()}
    assert set(rows) == {"DATA_ERROR", "PROVIDER_ERROR", "RISK_BLOCK"}
    assert rows["RISK_BLOCK"].severity == "CRITICAL"
    assert rows["RISK_BLOCK"].message == "GLOBAL_KILL_SWITCH_ACTIVATED"


def test_closing_a_paper_position_through_the_api_emits_a_persisted_exit_alert(client, db_session):
    from tests.phase8_helpers import PRED, QUOTE, RISK_OK, request
    from api.main import paper_service

    paper_service.__init__()
    paper_service.start()
    entry = paper_service.enter(request(), quote=QUOTE, setup_status="EXECUTABLE_SIMULATION",
                                risk_decision=RISK_OK, data_quality="VALID",
                                provider_status="ONLINE", prediction=PRED)
    position_id = entry.order.position_id
    assert client.post(f"/paper/close-position/{position_id}?price=1.11").status_code == 200
    row = db_session.query(DashboardAlertRecord).one()
    assert row.alert_type == "EXIT_TRIGGER" and row.symbol == "EURUSD"
    assert client.get("/dashboard/alerts").json()["data"]["items"][0]["alert_type"] == "EXIT_TRIGGER"
    paper_service.__init__()
