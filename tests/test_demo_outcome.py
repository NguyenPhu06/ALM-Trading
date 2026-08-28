"""DEMO outcomes (section 5).

What the DEMO trade actually did, net of what it actually cost. Every figure here
comes from the journal entry the Phase 16 execution path wrote, so a DEMO outcome
cannot claim a fill the broker never reported.
"""
import pytest
from datetime import timedelta

from execution.demo.journal import DemoTradeJournal
from execution.mt5.order_result import ExecutionStatus, OrderResult
from tests.phase16_helpers import LONDON_MOMENT, live_context, order, service_for
from validation.comparison import DemoOutcomeView


def journal_entry(*, filled_price=1.10030, exit_price=1.10500, pnl=9.0, gross_pnl=10.0,
                  commission=-0.8, swap=-0.15, mae=-0.0008, mfe=0.0031,
                  requested_price=1.10024, exit_reason="TAKE_PROFIT", hours=2):
    journal = DemoTradeJournal()
    request = order()
    result = OrderResult(request.request_id, ExecutionStatus.FILLED, "EURUSD", "BUY", 0.02,
                         filled_volume=0.02, requested_price=requested_price,
                         filled_price=filled_price, broker_ticket=700001)
    journal.open(request=request, result=result, market_snapshot={"spread": 0.00012},
                 feature_snapshot={"rsi": 55.0}, session="LONDON", regime="BULL",
                 now=LONDON_MOMENT)
    return journal.close(request.request_id, exit_reason=exit_reason, pnl=pnl,
                         gross_pnl=gross_pnl, mae=mae, mfe=mfe, commission=commission,
                         swap=swap, now=LONDON_MOMENT + timedelta(hours=hours),
                         exit_price=exit_price)


# ---------------------------------------------------------------- the figures
def test_a_demo_outcome_carries_every_declared_field():
    """Section 5, field for field."""
    payload = DemoOutcomeView.from_journal(journal_entry()).as_dict()
    for name in ("actual_entry", "actual_exit", "actual_pnl", "actual_mfe", "actual_mae",
                 "actual_duration", "actual_spread", "actual_slippage", "commission",
                 "swap", "net_actual_pnl"):
        assert name in payload


def test_the_actual_entry_is_the_broker_fill():
    view = DemoOutcomeView.from_journal(journal_entry(filled_price=1.10030))
    assert view.actual_entry == pytest.approx(1.10030)


def test_the_slippage_is_fill_minus_request():
    view = DemoOutcomeView.from_journal(
        journal_entry(filled_price=1.10030, requested_price=1.10024))
    assert view.actual_slippage == pytest.approx(0.00006)


def test_the_duration_comes_from_the_journal():
    view = DemoOutcomeView.from_journal(journal_entry(hours=3))
    assert view.actual_duration == pytest.approx(10800.0)


def test_the_costs_are_carried_through():
    view = DemoOutcomeView.from_journal(journal_entry(commission=-0.8, swap=-0.15))
    assert view.commission == pytest.approx(-0.8) and view.swap == pytest.approx(-0.15)


def test_the_total_cost_is_the_sum_of_its_parts():
    view = DemoOutcomeView.from_journal(
        journal_entry(commission=-0.8, swap=-0.15, filled_price=1.10034))
    assert view.total_cost == pytest.approx(0.8 + 0.15 + 0.0001, abs=1e-9)


def test_the_net_pnl_is_the_journal_net():
    view = DemoOutcomeView.from_journal(journal_entry(pnl=9.0, gross_pnl=10.0))
    assert view.actual_pnl == pytest.approx(10.0)
    assert view.net_actual_pnl == pytest.approx(9.0)


def test_a_missing_net_is_derived_from_gross_and_cost():
    view = DemoOutcomeView.from_journal(
        journal_entry(pnl=None, gross_pnl=10.0, commission=-0.8, swap=-0.15))
    assert view.net_actual_pnl == pytest.approx(9.05)


def test_the_exit_reason_is_recorded():
    view = DemoOutcomeView.from_journal(journal_entry(exit_reason="STOP_LOSS"))
    assert view.exit_reason == "STOP_LOSS"


def test_an_unmeasured_figure_stays_none_rather_than_zero():
    """A missing exit is not a flat exit."""
    view = DemoOutcomeView.from_journal(journal_entry(exit_price=None))
    assert view.actual_exit is None


# ---------------------------------------------------------------- end to end
def test_a_real_demo_fill_produces_an_outcome(db_session):
    service, _ = service_for(db_session)
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.executed

    service.journal.close(request.request_id, exit_reason="TAKE_PROFIT", pnl=9.0,
                          gross_pnl=10.0, mae=-0.0005, mfe=0.0022, exit_price=1.1050)
    view = DemoOutcomeView.from_journal(service.journal.get(request.request_id))

    assert view.request_id == request.request_id
    assert view.actual_entry == pytest.approx(1.10024)
    assert view.net_actual_pnl == pytest.approx(9.0)
    assert view.exit_reason == "TAKE_PROFIT"
