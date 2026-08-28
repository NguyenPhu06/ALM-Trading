"""Idempotency (sections 12 and 33).

One signal, one order. The request id is derived from the decision, so a repeat
is recognised rather than merely improbable, and the second submission is
blocked before it reaches the broker.
"""
import pytest

from database.models import ExecutionResultRecord
from execution.demo.idempotency import (
    DUPLICATE_EXECUTION_REQUEST, IDEMPOTENCY_STORE_UNAVAILABLE, IdempotencyRegistry,
)
from execution.demo.order import DemoOrderRequest, execution_request_id
from execution.mt5.order_request import ExecutionIntent, OrderSide
from tests.phase16_helpers import armed, chain_for, context, live_context, order, service_for


# --------------------------------------------------------------- the identity
def test_the_same_decision_produces_the_same_id():
    first = execution_request_id(signal_id="s1", symbol="EURUSD", side=OrderSide.BUY,
                                 trading_day="2026-08-27")
    second = execution_request_id(signal_id="s1", symbol="EURUSD", side=OrderSide.BUY,
                                  trading_day="2026-08-27")
    assert first == second


def test_the_id_is_independent_of_volume():
    """Re-sizing the same signal is still the same decision, not a new one."""
    small = order(volume=0.01)
    large = order(volume=0.05)
    assert small.request_id == large.request_id


def test_a_different_signal_produces_a_different_id():
    assert order(signal_id="s1").request_id != order(signal_id="s2").request_id


def test_a_different_side_produces_a_different_id():
    assert order(side=OrderSide.BUY).request_id != order(side=OrderSide.SELL).request_id


def test_a_different_trading_day_produces_a_different_id():
    """The same signal tomorrow is a new decision."""
    assert order(trading_day="2026-08-27").request_id != order(trading_day="2026-08-28").request_id


def test_a_dca_level_is_a_different_order_not_a_duplicate():
    first = order(intent=ExecutionIntent.DCA, sequence=1)
    second = order(intent=ExecutionIntent.DCA, sequence=2)
    assert first.request_id != second.request_id


def test_an_id_cannot_be_derived_without_a_signal():
    with pytest.raises(ValueError, match="signal id"):
        execution_request_id(signal_id="", symbol="EURUSD", side=OrderSide.BUY)


# --------------------------------------------------------------- the registry
def test_a_fresh_id_is_allowed():
    assert IdempotencyRegistry().check("abc").allowed


def test_a_registered_id_is_a_duplicate():
    registry = IdempotencyRegistry()
    registry.register("abc")
    verdict = registry.check("abc")
    assert verdict.duplicate and DUPLICATE_EXECUTION_REQUEST in verdict.reasons


def test_registering_twice_reports_the_duplicate():
    registry = IdempotencyRegistry()
    assert registry.register("abc").allowed
    assert not registry.register("abc").allowed


def test_an_unreadable_store_blocks_rather_than_assumes_new():
    class Broken:
        def execution_exists(self, request_id):
            raise RuntimeError("database down")

    verdict = IdempotencyRegistry(Broken()).check("abc")
    assert not verdict.allowed
    assert IDEMPOTENCY_STORE_UNAVAILABLE in verdict.reasons


def test_a_store_without_the_lookup_blocks():
    verdict = IdempotencyRegistry(object()).check("abc")
    assert not verdict.allowed
    assert IDEMPOTENCY_STORE_UNAVAILABLE in verdict.reasons


def test_forgetting_releases_an_id_that_never_reached_a_broker():
    registry = IdempotencyRegistry()
    registry.register("abc")
    registry.forget("abc")
    assert registry.check("abc").allowed


# ---------------------------------------------------------------- end to end
def test_the_second_submission_of_a_signal_is_blocked(db_session):
    service, fake = service_for(db_session)
    first = order()
    assert service.submit(first, live_context(service, first)).executed
    assert len(fake.sent) == 1

    again = order()
    outcome = service.submit(again, live_context(service, again))
    assert not outcome.approved
    assert DUPLICATE_EXECUTION_REQUEST in outcome.reasons
    assert len(fake.sent) == 1, "the broker must not see the same signal twice"


def test_the_duplicate_refusal_is_persisted(db_session):
    service, _ = service_for(db_session)
    first = order()
    service.submit(first, live_context(service, first))
    again = order()
    service.submit(again, live_context(service, again))

    rows = (db_session.query(ExecutionResultRecord)
            .filter(ExecutionResultRecord.request_id == again.request_id).all())
    assert any(row.status == "BLOCKED" for row in rows)


def test_a_duplicate_raises_an_alert(db_session):
    from database.models import DashboardAlertRecord

    service, _ = service_for(db_session)
    first = order()
    service.submit(first, live_context(service, first))
    again = order()
    service.submit(again, live_context(service, again))

    types = {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}
    assert "DUPLICATE_ORDER_BLOCKED" in types


def test_a_blocked_proposal_can_be_retried_after_the_gate_is_fixed(db_session):
    """A refusal never reached the broker, so it is not a prior submission."""
    service, fake = service_for(db_session)
    request = order()
    blocked = service.submit(request, live_context(service, request, risk_allowed=False))
    assert not blocked.approved and fake.sent == []

    retried = order()
    outcome = service.submit(retried, live_context(service, retried))
    assert outcome.executed, outcome.reasons
    assert len(fake.sent) == 1


def test_a_new_signal_is_not_blocked_by_a_previous_one(db_session):
    service, fake = service_for(db_session)
    first = order(signal_id="signal-001")
    service.submit(first, live_context(service, first))
    second = order(signal_id="signal-002")
    outcome = service.submit(second, live_context(service, second))
    assert outcome.executed and len(fake.sent) == 2
