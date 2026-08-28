"""Execution states and the order lifecycle (sections 13 and 14).

Eleven states, forward-only transitions, and an append-only history. A blocked
order is never "retried into" an approved one: the next attempt is a new request
with its own id, and the audit trail keeps both.
"""
import pytest

from database.models import ExecutionAuditLogRecord, ExecutionResultRecord, ReconciliationRecordRow
from execution.demo.states import (
    ALLOWED_TRANSITIONS, TERMINAL_STATES, DemoExecutionState, ExecutionLifecycle,
    ExecutionStateError, state_for_result,
)
from execution.mt5.mock import FakeExecutionModule
from execution.mt5.order_result import ExecutionStatus, OrderResult
from tests.phase16_helpers import DEMO_SERVER, live_context, order, service_for


def lifecycle(**kwargs):
    return ExecutionLifecycle("r1", **kwargs)


# ---------------------------------------------------------------- the states
def test_the_eleven_declared_states_exist():
    assert {str(state) for state in DemoExecutionState} == {
        "PROPOSED", "APPROVED", "BLOCKED", "SUBMITTED", "ACCEPTED", "PARTIALLY_FILLED",
        "FILLED", "REJECTED", "CANCELLED", "ERROR", "RECONCILED"}


def test_every_state_has_a_transition_rule():
    assert set(ALLOWED_TRANSITIONS) == set(DemoExecutionState)


def test_the_terminal_states_go_nowhere():
    for state in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[state] == frozenset()


# ------------------------------------------------------------ the transitions
def test_the_happy_path_is_allowed():
    live = lifecycle()
    for state in (DemoExecutionState.APPROVED, DemoExecutionState.SUBMITTED,
                  DemoExecutionState.FILLED, DemoExecutionState.RECONCILED):
        live.advance(state)
    assert live.state is DemoExecutionState.RECONCILED and live.terminal


def test_a_skipped_state_is_refused():
    with pytest.raises(ExecutionStateError):
        lifecycle().advance(DemoExecutionState.FILLED)


def test_a_reversed_state_is_refused():
    live = lifecycle()
    live.advance(DemoExecutionState.APPROVED)
    with pytest.raises(ExecutionStateError):
        live.advance(DemoExecutionState.PROPOSED)


def test_a_blocked_order_cannot_become_approved():
    live = lifecycle()
    live.advance(DemoExecutionState.BLOCKED, reasons=("KILL_SWITCH_ENGAGED",))
    with pytest.raises(ExecutionStateError):
        live.advance(DemoExecutionState.APPROVED)


def test_a_partial_fill_may_complete_or_reconcile():
    live = lifecycle()
    live.advance(DemoExecutionState.APPROVED)
    live.advance(DemoExecutionState.SUBMITTED)
    live.advance(DemoExecutionState.PARTIALLY_FILLED)
    assert live.can_advance(DemoExecutionState.FILLED)
    assert live.can_advance(DemoExecutionState.RECONCILED)


def test_the_history_is_append_only_and_names_the_actor():
    live = lifecycle()
    live.advance(DemoExecutionState.APPROVED, actor="Phu", reasons=("verified",))
    live.advance(DemoExecutionState.CANCELLED, actor="Phu", reasons=("changed mind",))
    history = live.history
    assert [transition.state for transition in history] == [
        DemoExecutionState.PROPOSED, DemoExecutionState.APPROVED, DemoExecutionState.CANCELLED]
    assert history[1].actor == "Phu" and history[1].previous is DemoExecutionState.PROPOSED


# -------------------------------------------------------------- result mapping
@pytest.mark.parametrize("status,expected", [
    (ExecutionStatus.FILLED, DemoExecutionState.FILLED),
    (ExecutionStatus.PARTIAL, DemoExecutionState.PARTIALLY_FILLED),
    (ExecutionStatus.SUBMITTED, DemoExecutionState.ACCEPTED),
    (ExecutionStatus.REJECTED, DemoExecutionState.REJECTED),
    (ExecutionStatus.BLOCKED, DemoExecutionState.BLOCKED),
    (ExecutionStatus.FAILED, DemoExecutionState.ERROR),
])
def test_a_broker_status_maps_onto_a_state(status, expected):
    result = OrderResult("r1", status, "EURUSD", "BUY", 0.01)
    assert state_for_result(result) is expected


def test_an_unrecognised_status_maps_to_error():
    """Fail-closed: an unknown broker state is an error, not a fill."""
    assert state_for_result(object()) is DemoExecutionState.ERROR


# ------------------------------------------------------------- the full path
def test_a_filled_order_ends_reconciled(db_session):
    service, _ = service_for(db_session)
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.state is DemoExecutionState.RECONCILED
    assert [str(step.state) for step in outcome.lifecycle.history] == [
        "PROPOSED", "APPROVED", "SUBMITTED", "FILLED", "RECONCILED"]


def test_a_blocked_order_ends_blocked(db_session):
    service, _ = service_for(db_session)
    request = order()
    outcome = service.submit(request, live_context(service, request, risk_allowed=False))
    assert outcome.state is DemoExecutionState.BLOCKED


def test_a_broker_rejection_ends_rejected(db_session):
    service, _ = service_for(db_session, module=FakeExecutionModule(
        retcode=10019, server=DEMO_SERVER))
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.state is DemoExecutionState.REJECTED
    assert outcome.result.error_code == "MT5_RETCODE_10019"


def test_a_transport_failure_ends_in_error(db_session):
    service, _ = service_for(db_session, module=FakeExecutionModule(
        raise_on_send=True, server=DEMO_SERVER))
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.state is DemoExecutionState.ERROR
    assert outcome.result.error_code == "ORDER_SEND_EXCEPTION"


def test_a_partial_fill_is_reported_as_partially_filled(db_session):
    service, _ = service_for(db_session, module=FakeExecutionModule(
        retcode=10010, fill_volume=0.01, server=DEMO_SERVER))
    request = order(volume=0.02)
    outcome = service.submit(request, live_context(service, request))
    assert outcome.state is DemoExecutionState.PARTIALLY_FILLED
    assert outcome.result.filled_volume == 0.01


# ------------------------------------------------------- the recorded result
def test_the_execution_result_records_every_declared_field(db_session):
    """Section 13, field for field."""
    service, _ = service_for(db_session)
    request = order()
    outcome = service.submit(request, live_context(service, request))
    row = db_session.query(ExecutionResultRecord).one()

    assert row.request_id == request.request_id
    assert row.broker_ticket == 700001
    assert row.status == "FILLED"
    assert row.filled_volume == 0.02
    assert row.requested_price == pytest.approx(1.10024)
    assert row.filled_price == pytest.approx(1.10024)
    assert row.error_code is None and row.error_message is not None
    assert row.timestamp is not None and row.environment == "DEMO"
    # Slippage, commission and swap live on the journal entry alongside the fill.
    entry = service.journal.get(request.request_id)
    assert entry is not None and entry.slippage == pytest.approx(0.0, abs=1e-9)


def test_every_stage_is_persisted_before_the_next_begins(db_session):
    service, _ = service_for(db_session)
    request = order()
    service.submit(request, live_context(service, request))
    stages = [row.stage for row in db_session.query(ExecutionAuditLogRecord)
              .order_by(ExecutionAuditLogRecord.id).all()]
    assert stages.index("GATES") < stages.index("EXECUTION") < stages.index("RECONCILIATION")


def test_a_refusal_is_as_fully_audited_as_a_fill(db_session):
    service, _ = service_for(db_session)
    request = order()
    service.submit(request, live_context(service, request, risk_allowed=False))
    stages = {row.stage for row in db_session.query(ExecutionAuditLogRecord).all()}
    assert {"MODE", "GATES", "PROPOSAL", "RESULT"} <= stages
    assert db_session.query(ExecutionResultRecord).count() == 1
