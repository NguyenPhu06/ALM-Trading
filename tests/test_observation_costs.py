"""Realistic execution costs (section 7).

Gross PnL is never the final performance number. Every figure the system reports
as performance is `net_hypothetical_pnl`, after spread, commission, slippage and
swap.
"""
from datetime import timedelta

import pytest

from observation.outcome import ExecutionCosts, ForwardOutcomeEngine, costs_from_settings
from tests.phase14_helpers import NOW, candles, observation

LATER = NOW + timedelta(hours=1, minutes=1)


def window(drift: float = 0.00006):
    return candles(14, start=NOW, step_minutes=5, drift=drift)


# ---------------------------------------------------------- the cost profile
def test_the_cost_profile_names_every_component():
    costs = ExecutionCosts(spread=0.0001, commission=0.00002, slippage=0.00003, swap=0.00001)
    payload = costs.as_dict()
    for name in ("spread", "commission", "slippage", "swap", "total"):
        assert name in payload


def test_the_total_is_the_sum_of_the_components():
    costs = ExecutionCosts(spread=0.0001, commission=0.00002, slippage=0.00003, swap=0.00001)
    assert costs.total == pytest.approx(0.00016)


def test_costs_are_never_negative():
    costs = ExecutionCosts(spread=-0.0001, commission=-0.00002)
    assert costs.total == pytest.approx(0.00012)


def test_the_cost_profile_comes_from_configuration():
    costs = costs_from_settings(spread=0.0001)
    assert costs.spread == pytest.approx(0.0001)
    assert costs.slippage >= 0


def test_swap_accrues_with_holding_time():
    engine = ForwardOutcomeEngine()
    engine.swap_per_day = 0.001
    overnight = engine.costs_for(spread=0.0, holding=timedelta(days=1))
    minutes = engine.costs_for(spread=0.0, holding=timedelta(minutes=5))
    assert overnight.swap > minutes.swap
    assert overnight.swap == pytest.approx(0.001)


def test_a_zero_length_hold_accrues_no_swap():
    engine = ForwardOutcomeEngine()
    engine.swap_per_day = 0.001
    assert engine.costs_for(spread=0.0, holding=timedelta()).swap == 0.0


# ------------------------------------------------------- net is the headline
def test_net_is_gross_minus_cost():
    outcome = ForwardOutcomeEngine().resolve(observation(), window(), now=LATER).outcome
    assert outcome.net_hypothetical_pnl == pytest.approx(
        outcome.future_return - outcome.estimated_cost)


def test_net_is_always_below_gross_when_a_cost_exists():
    outcome = ForwardOutcomeEngine().resolve(observation(), window(), now=LATER).outcome
    assert outcome.estimated_cost > 0
    assert outcome.net_hypothetical_pnl < outcome.hypothetical_pnl


def test_a_move_that_does_not_clear_costs_is_not_profitable():
    """The point of section 7: a small gross win is a net loss."""
    tiny = candles(14, start=NOW, step_minutes=5, drift=0.0000001)
    outcome = ForwardOutcomeEngine().resolve(observation(), tiny, now=LATER).outcome
    assert outcome.future_return > 0, "gross is positive"
    assert outcome.net_hypothetical_pnl < 0, "net is not"
    assert not outcome.profitable


def test_profitable_is_decided_on_net_not_gross():
    outcome = ForwardOutcomeEngine().resolve(observation(), window(0.0002), now=LATER).outcome
    assert outcome.profitable is (outcome.net_hypothetical_pnl > 0)


def test_the_spread_the_observation_saw_is_the_spread_that_is_charged():
    outcome = ForwardOutcomeEngine().resolve(observation(), window(), now=LATER).outcome
    assert outcome.spread == pytest.approx(0.00010)
    assert outcome.context["costs"]["spread"] == pytest.approx(0.00010)


def test_a_wider_spread_produces_a_worse_net_result():
    from dataclasses import replace

    engine = ForwardOutcomeEngine()
    narrow = engine.resolve(observation(), window(), now=LATER).outcome
    wide_observation = replace(observation(), context={"spread": 0.00080})
    wide = engine.resolve(wide_observation, window(), now=LATER).outcome
    assert wide.net_hypothetical_pnl < narrow.net_hypothetical_pnl
    assert wide.future_return == pytest.approx(narrow.future_return), "gross is unchanged"


def test_every_cost_component_is_reported_alongside_the_outcome():
    outcome = ForwardOutcomeEngine().resolve(observation(), window(), now=LATER).outcome
    costs = outcome.context["costs"]
    assert set(costs) == {"spread", "commission", "slippage", "swap", "total"}
