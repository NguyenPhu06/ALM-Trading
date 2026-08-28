"""SHADOW vs DEMO (section 6).

Nine differences, each classified. The classification is the point: a strategy
that was right and filled badly needs a different response from one that was
wrong, and only an attribution tells them apart.

`NONE` is a real verdict here, not a fallback.
"""
from datetime import timedelta

import pytest

from database.models import ShadowDemoComparisonRecord
from database.repositories.validation import ValidationRepository
from validation.comparison import (
    DemoOutcomeView, DifferenceKind, NOT_COMPARABLE, ShadowDemoComparator,
)
from tests.phase16_helpers import order
from tests.phase17_helpers import EXIT_MOMENT, recorder, shadow_signal


def pair(*, shadow_exit=1.10500, demo_entry=1.10030, demo_exit=1.10490,
         demo_slippage=0.00006, demo_spread=0.00012, demo_commission=-0.8,
         demo_swap=-0.15, demo_pnl=0.00450, demo_mae=-0.0008, demo_mfe=0.0031,
         demo_duration=7200.0, demo_side="BUY", highs=None, lows=None):
    live = recorder()
    signal = shadow_signal(recorder_=live)
    shadow = live.resolve(signal, exit_price=shadow_exit, exit_time=EXIT_MOMENT,
                          highs=highs, lows=lows)
    demo = DemoOutcomeView(
        request_id=signal.demo_execution_request_id, symbol="EURUSD", side=demo_side,
        actual_entry=demo_entry, actual_exit=demo_exit, actual_pnl=demo_pnl,
        actual_mfe=demo_mfe, actual_mae=demo_mae, actual_duration=demo_duration,
        actual_spread=demo_spread, actual_slippage=demo_slippage,
        commission=demo_commission, swap=demo_swap, net_actual_pnl=demo_pnl,
        exit_reason="TAKE_PROFIT")
    return signal, shadow, demo


def compare(**kwargs):
    signal, shadow, demo = pair(**kwargs)
    return ShadowDemoComparator().compare(signal, shadow, demo)


# ------------------------------------------------------------- the differences
def test_all_nine_differences_are_measured():
    payload = compare().as_dict()
    for name in ("signal_difference", "entry_difference", "exit_difference",
                 "slippage_difference", "cost_difference", "pnl_difference",
                 "mae_difference", "mfe_difference", "time_difference"):
        assert name in payload


def test_the_entry_difference_is_demo_minus_shadow():
    result = compare(demo_entry=1.10030)
    assert result.entry_difference == pytest.approx(1.10030 - 1.10024)


def test_the_exit_difference_is_demo_minus_shadow():
    result = compare(shadow_exit=1.10500, demo_exit=1.10490)
    assert result.exit_difference == pytest.approx(-0.0001)


def test_the_time_difference_is_measured():
    result = compare(demo_duration=7500.0)
    assert result.time_difference == pytest.approx(300.0)


# ------------------------------------------------------------ the attribution
def test_a_clean_pairing_classifies_as_none():
    result = compare(demo_entry=1.10025, demo_exit=1.10499, demo_slippage=0.00002,
                     demo_spread=0.00012, demo_commission=0.0, demo_swap=0.0)
    assert result.kinds == (DifferenceKind.NONE,)
    assert result.matched is True
    assert result.primary is DifferenceKind.NONE


def test_a_different_side_is_a_signal_error():
    result = compare(demo_side="SELL")
    assert DifferenceKind.SIGNAL_ERROR in result.kinds
    assert result.signal_difference is True


def test_a_bad_fill_is_an_execution_error():
    result = compare(demo_entry=1.10060)
    assert DifferenceKind.EXECUTION_ERROR in result.kinds


def test_a_moved_exit_is_market_movement_not_a_broker_problem():
    """The same exit rule fired at a different price because price moved."""
    result = compare(shadow_exit=1.10500, demo_exit=1.10400)
    assert DifferenceKind.MARKET_MOVEMENT in result.kinds
    assert DifferenceKind.EXECUTION_ERROR not in result.kinds


def test_a_wide_spread_is_a_spread_error():
    result = compare(demo_spread=0.0010)
    assert DifferenceKind.SPREAD_ERROR in result.kinds


def test_excess_slippage_is_a_slippage_error():
    result = compare(demo_slippage=0.0009)
    assert DifferenceKind.SLIPPAGE_ERROR in result.kinds


def test_excess_cost_is_a_cost_error():
    result = compare(demo_commission=-5.0)
    assert DifferenceKind.COST_ERROR in result.kinds


def test_a_late_exit_is_a_timing_error():
    result = compare(demo_duration=7200.0 + 600)
    assert DifferenceKind.TIMING_ERROR in result.kinds


def test_several_kinds_are_reported_together():
    result = compare(demo_entry=1.10060, demo_spread=0.0010, demo_duration=9000.0)
    assert {DifferenceKind.EXECUTION_ERROR, DifferenceKind.SPREAD_ERROR,
            DifferenceKind.TIMING_ERROR} <= set(result.kinds)


def test_a_missing_figure_is_not_treated_as_zero():
    signal, shadow, demo = pair()
    from dataclasses import replace

    result = ShadowDemoComparator().compare(signal, shadow, replace(demo, actual_exit=None))
    assert result.exit_difference is None


# ------------------------------------------------------- the unexecuted signals
def test_a_signal_demo_never_took_is_still_recorded():
    """The blocked population is exactly what the gates removed."""
    from tests.phase16_helpers import armed, chain_for, context

    blocked = chain_for(armed()).evaluate(order(), context(risk_allowed=False))
    signal = shadow_signal(decision=blocked, ctx=context(risk_allowed=False))
    result = ShadowDemoComparator().compare_unexecuted(signal)

    assert result.kinds == (DifferenceKind.SIGNAL_ERROR,)
    assert result.details["reason"] == NOT_COMPARABLE
    assert "RISK_ENGINE_BLOCKED" in result.details["blocked_reasons"]


# ------------------------------------------------------------- the aggregate
def test_an_empty_population_reports_no_evidence():
    summary = ShadowDemoComparator.summarize([])
    assert summary["samples"] == 0 and summary["reliable"] is False
    assert "NO_COMPARISONS" in summary["reasons"]


def test_a_handful_of_pairings_is_an_anecdote():
    summary = ShadowDemoComparator.summarize([compare() for _ in range(5)])
    assert summary["samples"] == 5 and summary["reliable"] is False
    assert "INSUFFICIENT_SAMPLES" in summary["reasons"]


def test_enough_pairings_become_a_measurement():
    summary = ShadowDemoComparator.summarize([compare() for _ in range(30)])
    assert summary["reliable"] is True and summary["reasons"] == []
    assert summary["kinds"], "the attribution counts are the useful part"


def test_the_summary_counts_each_kind():
    rows = [compare(), compare(demo_slippage=0.0009), compare(demo_slippage=0.0009)]
    summary = ShadowDemoComparator.summarize(rows)
    assert summary["kinds"]["SLIPPAGE_ERROR"] == 2


# --------------------------------------------------------------- persistence
def test_a_comparison_persists(db_session):
    repository = ValidationRepository(db_session)
    repository.save_comparison(compare(demo_entry=1.10060))
    row = db_session.query(ShadowDemoComparisonRecord).one()
    assert row.primary_kind == "EXECUTION_ERROR"
    assert row.entry_difference == pytest.approx(0.00036)
    assert row.matched is False


def test_comparisons_can_be_read_back(db_session):
    repository = ValidationRepository(db_session)
    repository.save_comparison(compare())
    assert len(repository.recent_comparisons()) == 1
