"""Reconciliation compares request, broker result and resulting position."""
from types import SimpleNamespace

import pytest

from database.models import ReconciliationRecordRow
from execution.mt5.order_result import ExecutionStatus, OrderResult
from execution.mt5.reconciliation import Reconciler, ReconciliationStatus
from tests.phase11_helpers import order, service_for


def result(**overrides):
    base = dict(request_id="r1", status=ExecutionStatus.FILLED, symbol="EURUSD", side="BUY",
                requested_volume=0.01, filled_volume=0.01, requested_price=1.10024,
                filled_price=1.10024, sl=1.09000, tp=1.11000, broker_ticket=700001)
    base.update(overrides)
    return OrderResult(**base)


def position(**overrides):
    base = dict(ticket=700001, volume=0.01, profit=1.25, stop_loss=1.09000, take_profit=1.11000)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_a_clean_fill_reconciles():
    record = Reconciler().reconcile(order(), result(), position())
    assert record.status is ReconciliationStatus.MATCHED and record.matched
    assert record.reasons == () and all(record.checks.values())
    assert record.broker_ticket == 700001


def test_a_volume_mismatch_is_reported():
    record = Reconciler().reconcile(order(volume=0.02), result(filled_volume=0.01), position())
    assert record.status is ReconciliationStatus.MISMATCHED
    assert "VOLUME_MISMATCH" in record.reasons
    assert record.differences["volume"] == pytest.approx(0.01)


def test_a_price_deviation_is_reported():
    record = Reconciler().reconcile(order(price=1.10000), result(requested_price=1.10000,
                                                                filled_price=1.20000), position())
    assert "PRICE_DEVIATION" in record.reasons
    assert record.differences["price"] == pytest.approx(0.1)


def test_a_missing_ticket_is_reported():
    record = Reconciler().reconcile(order(), result(broker_ticket=None), position(ticket=None))
    assert "MISSING_BROKER_TICKET" in record.reasons


def test_a_missing_position_is_its_own_status():
    record = Reconciler().reconcile(order(), result(), None)
    assert record.status is ReconciliationStatus.POSITION_MISSING
    assert "POSITION_MISSING" in record.reasons


def test_a_position_volume_mismatch_is_reported():
    record = Reconciler().reconcile(order(), result(), position(volume=0.05))
    assert "POSITION_VOLUME_MISMATCH" in record.reasons


def test_a_position_ticket_mismatch_is_reported():
    record = Reconciler().reconcile(order(), result(), position(ticket=999999))
    assert "POSITION_TICKET_MISMATCH" in record.reasons


def test_pnl_is_captured_from_the_position():
    record = Reconciler().reconcile(order(), result(), position(profit=7.5))
    assert record.differences["pnl"] == 7.5 and record.checks["pnl"]


def test_a_missing_pnl_is_reported():
    record = Reconciler().reconcile(order(), result(), position(profit=None))
    assert "PNL_UNAVAILABLE" in record.reasons


def test_a_stop_loss_the_broker_did_not_set_is_reported():
    record = Reconciler().reconcile(order(sl=1.09000), result(), position(stop_loss=None))
    assert "SL_NOT_SET" in record.reasons


def test_a_take_profit_mismatch_is_reported():
    record = Reconciler().reconcile(order(tp=1.11000), result(), position(take_profit=1.50000))
    assert "TP_MISMATCH" in record.reasons


def test_omitted_stops_reconcile_cleanly():
    record = Reconciler().reconcile(order(sl=None, tp=None), result(sl=None, tp=None),
                                    position(stop_loss=None, take_profit=None))
    assert record.checks["sl"] and record.checks["tp"]


def test_a_blocked_order_is_not_applicable():
    blocked = result(status=ExecutionStatus.BLOCKED, filled_volume=0.0, broker_ticket=None)
    record = Reconciler().reconcile(order(), blocked, None)
    assert record.status is ReconciliationStatus.NOT_APPLICABLE
    assert "ORDER_NOT_EXECUTED" in record.reasons


def test_tolerances_are_configurable():
    lenient = Reconciler(volume_tolerance=0.05, price_tolerance=1.0)
    record = lenient.reconcile(order(volume=0.02), result(filled_volume=0.01), position(volume=0.01))
    assert record.matched


# ------------------------------------------------------------------- service
def test_the_service_persists_a_reconciliation_record(db_session):
    service, _ = service_for(db_session)
    service.execute(order())
    row = db_session.query(ReconciliationRecordRow).one()
    assert row.status == "MATCHED" and row.broker_ticket == 700001 and row.symbol == "EURUSD"


def test_a_reconciliation_failure_raises_an_alert(db_session):
    from database.models import DashboardAlertRecord
    from execution.mt5.mock import FakeExecutionModule
    from tests.phase11_helpers import DEMO_SERVER

    # The broker fills a different size than requested.
    service, _ = service_for(db_session, module=FakeExecutionModule(
        fill_volume=0.09, server=DEMO_SERVER))
    outcome = service.execute(order(volume=0.01))
    assert not outcome.reconciliation.matched
    types = {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}
    assert "RECONCILIATION_FAILED" in types


def test_reconciliation_reports_but_never_repairs(db_session):
    """A mismatch is recorded and alerted; nothing is corrected on the broker."""
    from execution.mt5.mock import FakeExecutionModule
    from tests.phase11_helpers import DEMO_SERVER

    service, fake = service_for(db_session, module=FakeExecutionModule(
        fill_volume=0.09, server=DEMO_SERVER))
    service.execute(order(volume=0.01))
    assert len(fake.sent) == 1, "no corrective order may be sent"
