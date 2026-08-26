"""Every execution is fully audited, and no credential ever reaches the trail."""
import pytest
from pydantic import SecretStr

from database.base import Base
from database.models import ExecutionAuditLogRecord, ExecutionRequestRecord, ExecutionResultRecord
from database.repositories.execution import ExecutionRepository
from execution.mt5.execution_service import (
    STAGE_DECISION,
    STAGE_EXECUTION,
    STAGE_RECONCILIATION,
    STAGE_REQUEST,
    STAGE_RESULT,
    STAGE_VALIDATION,
)
from tests.phase11_helpers import BASE, order, service_for, settings

SECRET = "super-secret-mt5-password"
CREDENTIAL_TOKENS = ("password", "secret", "credential", "api_key", "token")


def stages(db_session, request_id=None):
    repository = ExecutionRepository(db_session)
    rows = repository.audit_trail(request_id) if request_id else repository.recent_audit(100)
    return [row.stage for row in rows]


def test_a_successful_execution_records_every_stage(db_session):
    service, _ = service_for(db_session)
    outcome = service.execute(order())
    assert stages(db_session, outcome.request.request_id) == [
        STAGE_REQUEST, STAGE_VALIDATION, STAGE_DECISION,
        STAGE_EXECUTION, STAGE_RESULT, STAGE_RECONCILIATION,
    ]


def test_a_refused_execution_is_audited_through_to_the_result(db_session):
    service, _ = service_for(db_session, settings())
    outcome = service.execute(order())
    assert stages(db_session, outcome.request.request_id) == [
        STAGE_REQUEST, STAGE_VALIDATION, STAGE_DECISION, STAGE_RESULT,
    ]


def test_the_validation_entry_records_the_approval_and_the_reasons(db_session):
    service, _ = service_for(db_session, settings())
    outcome = service.execute(order())
    row = next(r for r in ExecutionRepository(db_session).audit_trail(outcome.request.request_id)
               if r.stage == STAGE_VALIDATION)
    assert row.approved is False
    assert "DEMO_TRADING_DISABLED" in row.reasons
    assert row.payload_json["checks"]["environment"] is False


def test_the_audit_entry_records_which_checks_passed(db_session):
    service, _ = service_for(db_session)
    outcome = service.execute(order())
    row = next(r for r in ExecutionRepository(db_session).audit_trail(outcome.request.request_id)
               if r.stage == STAGE_VALIDATION)
    assert row.approved is True
    assert all(row.payload_json["checks"].values())


def test_each_request_has_its_own_trail(db_session):
    service, _ = service_for(db_session)
    first = service.execute(order())
    second = service.execute(order(volume=0.02))
    assert first.request.request_id != second.request.request_id
    assert len(stages(db_session, first.request.request_id)) == 6
    assert len(stages(db_session, second.request.request_id)) == 6


def test_the_request_row_captures_the_submitted_order(db_session):
    service, _ = service_for(db_session)
    outcome = service.execute(order(volume=0.02, comment="manual check"))
    row = db_session.query(ExecutionRequestRecord).one()
    assert row.request_id == outcome.request.request_id
    assert row.symbol == "EURUSD" and row.side == "BUY" and row.volume == 0.02
    assert row.intent == "MANUAL_TEST" and row.comment == "manual check"
    assert row.environment == "DEMO"


def test_the_result_row_captures_the_broker_outcome(db_session):
    service, _ = service_for(db_session)
    service.execute(order())
    row = db_session.query(ExecutionResultRecord).one()
    assert row.status == "FILLED" and row.broker_ticket == 700001
    assert row.filled_volume == 0.01 and row.filled_price == pytest.approx(1.10024)


# ------------------------------------------------------------------- security
def test_no_execution_table_has_a_credential_column():
    offenders = [(table.name, column.name)
                 for table in Base.metadata.sorted_tables
                 if table.name.startswith(("execution_", "reconciliation_", "kill_switch_"))
                 for column in table.columns
                 if any(token in column.name.lower() for token in CREDENTIAL_TOKENS)]
    assert offenders == [], offenders


def test_a_credential_placed_in_an_audit_payload_is_scrubbed(db_session):
    repository = ExecutionRepository(db_session)
    repository.save_audit("r1", "REQUEST",
                          {"symbol": "EURUSD", "password": SECRET,
                           "nested": {"api_key": "x", "volume": 0.01}})
    row = db_session.query(ExecutionAuditLogRecord).one()
    assert row.payload_json == {"symbol": "EURUSD", "nested": {"volume": 0.01}}
    assert SECRET not in str(row.payload_json)


def test_no_audit_row_contains_a_credential_after_a_real_execution(db_session):
    config = settings(armed=True, mt5_login=987654321, mt5_password=SecretStr(SECRET),
                      mt5_server="Exness-MT5Trial8")
    service, _ = service_for(db_session, config)
    service.execute(order())
    for row in db_session.query(ExecutionAuditLogRecord).all():
        text = str(row.payload_json)
        assert SECRET not in text
        assert "987654321" not in text


def test_execution_endpoints_never_return_a_credential(client):
    for path in ("/execution/status", "/execution/audit", "/execution/orders",
                 "/execution/kill-switch", "/dashboard/execution"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert SECRET not in response.text, path
        assert "987654321" not in response.text, path


def test_the_audit_endpoint_can_be_filtered_by_request(client, db_session):
    body = client.post("/execution/demo/test",
                       json={"symbol": "EURUSD", "side": "BUY", "volume": 0.01}).json()
    trail = client.get(f"/execution/audit?request_id={body['request_id']}").json()["data"]
    assert trail["count"] >= 3
    assert {item["request_id"] for item in trail["items"]} == {body["request_id"]}
