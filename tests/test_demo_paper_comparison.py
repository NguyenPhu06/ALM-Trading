"""Paper vs DEMO and DEMO vs OBSERVATION (sections 29 and 32).

The purpose is attribution, not scoring. "The strategy lost money" and "the
strategy was right and the fill was bad" call for opposite responses, and these
comparisons are what tells them apart.
"""
import pytest

from database.models import DemoPaperComparisonRecord
from database.repositories.demo import DemoTradingRepository
from execution.demo.comparison import (
    EXECUTION_ERROR, MODEL_ERROR, NOT_COMPARABLE, RISK_REJECTION, SIGNAL_QUALITY_ERROR,
    SLIPPAGE_ERROR, SPREAD_ERROR, STRATEGY_ERROR, ExecutionComparator,
)


def comparator(**kwargs):
    kwargs.setdefault("entry_tolerance", 0.0002)
    kwargs.setdefault("exit_tolerance", 0.0002)
    kwargs.setdefault("slippage_tolerance", 0.0003)
    return ExecutionComparator(**kwargs)


def compare(**overrides):
    payload = dict(request_id="r1", symbol="EURUSD", paper_entry=1.1000, demo_entry=1.1001,
                   paper_exit=1.1050, demo_exit=1.1049, spread=0.00012, slippage=0.0001,
                   commission=-0.8, swap=-0.15, paper_net_pnl=50.0, demo_net_pnl=48.0)
    payload.update(overrides)
    return comparator().compare(**payload)


# ------------------------------------------------------------- section 29
def test_a_close_fill_is_within_tolerance():
    result = compare()
    assert result.within_tolerance and result.reasons == ()


def test_the_entry_difference_is_reported():
    result = compare(demo_entry=1.1005)
    assert result.entry_difference == pytest.approx(0.0005)
    assert "ENTRY_OUTSIDE_TOLERANCE" in result.reasons
    assert not result.within_tolerance


def test_the_exit_difference_is_reported():
    result = compare(demo_exit=1.1040)
    assert result.exit_difference == pytest.approx(-0.0010)
    assert "EXIT_OUTSIDE_TOLERANCE" in result.reasons


def test_excess_slippage_is_reported():
    result = compare(slippage=0.0009)
    assert "SLIPPAGE_OUTSIDE_TOLERANCE" in result.reasons


def test_the_pnl_gap_is_the_cost_of_execution_reality():
    result = compare()
    assert result.pnl_difference == pytest.approx(-2.0)


def test_a_missing_side_is_not_comparable_rather_than_zero():
    result = compare(demo_entry=None)
    assert result.entry_difference is None
    assert "ENTRY_NOT_COMPARABLE" in result.reasons


def test_costs_are_carried_through():
    result = compare()
    assert result.commission == -0.8 and result.swap == -0.15 and result.spread == 0.00012


# ------------------------------------------------------------- section 32
def attribute(**overrides):
    payload = dict(request_id="r1", symbol="EURUSD", observation_expected=60.0,
                   paper_result=50.0, demo_result=48.0)
    payload.update(overrides)
    return comparator().attribute(**payload)


def test_a_worse_demo_result_than_paper_is_an_execution_error():
    result = attribute()
    assert EXECUTION_ERROR in result.errors
    assert result.paper_gap == pytest.approx(-2.0)


def test_the_observation_gap_covers_signal_and_execution():
    result = attribute()
    assert result.observation_gap == pytest.approx(-12.0)


def test_a_paper_result_short_of_the_observation_is_a_signal_error():
    result = attribute(observation_expected=100.0, paper_result=50.0, demo_result=49.0)
    assert SIGNAL_QUALITY_ERROR in result.errors


def test_an_excess_spread_is_attributed_to_spread():
    result = attribute(spread=0.0004, expected_spread=0.0001)
    assert SPREAD_ERROR in result.errors
    assert result.details["spread_excess"] == pytest.approx(0.0003)


def test_excess_slippage_is_attributed_to_slippage():
    result = attribute(slippage=0.0008)
    assert SLIPPAGE_ERROR in result.errors


def test_a_wrong_model_is_attributed_to_the_model():
    assert MODEL_ERROR in attribute(model_correct=False).errors


def test_a_wrong_strategy_is_attributed_to_the_strategy():
    assert STRATEGY_ERROR in attribute(strategy_correct=False).errors


def test_a_risk_rejection_is_named_as_such():
    assert RISK_REJECTION in attribute(risk_rejected=True).errors


def test_a_trade_that_never_happened_is_not_comparable():
    result = attribute(demo_result=None)
    assert NOT_COMPARABLE in result.errors


def test_a_clean_execution_attributes_nothing():
    result = attribute(observation_expected=48.0, paper_result=48.0, demo_result=48.0)
    assert result.errors == ()


# ------------------------------------------------------------- the aggregate
def test_an_empty_population_reports_no_evidence():
    summary = ExecutionComparator.summarize([])
    assert summary["samples"] == 0 and not summary["reliable"]
    assert "NO_COMPARISONS" in summary["reasons"]


def test_a_handful_of_fills_is_an_anecdote():
    summary = ExecutionComparator.summarize([compare() for _ in range(5)])
    assert summary["samples"] == 5 and not summary["reliable"]
    assert "INSUFFICIENT_SAMPLES" in summary["reasons"]


def test_enough_fills_become_a_measurement():
    summary = ExecutionComparator.summarize([compare() for _ in range(30)])
    assert summary["reliable"] and summary["reasons"] == []
    assert summary["mean_entry_difference"] == pytest.approx(0.0001)
    assert summary["mean_pnl_difference"] == pytest.approx(-2.0)


def test_the_worst_entry_difference_is_by_magnitude():
    rows = [compare(demo_entry=1.1000), compare(demo_entry=1.0990), compare(demo_entry=1.1003)]
    summary = ExecutionComparator.summarize(rows)
    assert summary["worst_entry_difference"] == pytest.approx(-0.0010)


# ------------------------------------------------------------- persistence
def test_a_comparison_persists_with_its_attribution(db_session):
    result = compare(demo_entry=1.1005)
    attribution = attribute()
    row = DemoTradingRepository(db_session).save_comparison(result, attribution)
    assert row.request_id == "r1"
    assert row.entry_difference == pytest.approx(0.0005)
    assert EXECUTION_ERROR in row.errors
    assert row.comparison_json["attribution"]["errors"]


def test_comparisons_can_be_read_back(db_session):
    repository = DemoTradingRepository(db_session)
    repository.save_comparison(compare())
    assert len(repository.recent_comparisons()) == 1
