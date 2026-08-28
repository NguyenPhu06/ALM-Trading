"""DCA safety on the execution path (section 10).

DCA is off by default. When it is on, every DCA order re-runs the complete gate
chain — not a shortened version of it — and is bounded by levels, aggregate
exposure and an invalidation condition. Nothing in this system multiplies size
after a loss.
"""
import pytest

from execution.demo.gates import DCA_DISABLED, DCA_INVALIDATED
from execution.demo.limits import (
    MAX_DCA_EXPOSURE, MAX_DCA_LEVELS, DemoRiskLimits,
)
from execution.demo.sizing import PositionSizer, SymbolContract
from execution.mt5.order_request import ExecutionIntent
from tests.phase16_helpers import armed, chain_for, context, live_context, order, service_for


def dca_order(**overrides):
    payload = dict(intent=ExecutionIntent.DCA, signal_id="signal-001", sequence=1)
    payload.update(overrides)
    return order(**payload)


def evaluate(config=None, request=None, **ctx):
    return chain_for(config or armed()).evaluate(request or dca_order(), context(**ctx))


# ---------------------------------------------------------------- off by default
def test_dca_is_disabled_by_default():
    assert armed().demo_dca_enabled is False


def test_a_dca_order_is_blocked_while_dca_is_disabled():
    decision = evaluate()
    assert not decision.approved
    assert DCA_DISABLED in decision.reasons
    assert "DcaSafetyGate" in decision.blocked_by


def test_a_non_dca_order_passes_the_dca_gate_trivially():
    decision = chain_for(armed()).evaluate(order(), context())
    gate = next(gate for gate in decision.gates if gate.name == "DcaSafetyGate")
    assert gate.passed and gate.reasons == ("NOT_A_DCA_ORDER",)


# ------------------------------------------------------------------ when enabled
def test_an_enabled_dca_order_within_its_budget_is_allowed():
    decision = evaluate(armed(demo_dca_enabled=True), dca_levels=1)
    assert decision.approved, decision.reasons


def test_the_level_limit_blocks_further_dca():
    config = armed(demo_dca_enabled=True)
    limits = DemoRiskLimits.from_config()
    decision = chain_for(config).evaluate(dca_order(), context(dca_levels=limits.max_dca_levels))
    assert not decision.approved and MAX_DCA_LEVELS in decision.reasons


def test_aggregate_dca_exposure_is_bounded():
    config = armed(demo_dca_enabled=True)
    limits = DemoRiskLimits.from_config()
    decision = chain_for(config).evaluate(
        dca_order(), context(dca_levels=1, dca_exposure=limits.max_total_dca_exposure,
                             order_notional=1_000.0))
    assert not decision.approved and MAX_DCA_EXPOSURE in decision.reasons


def test_an_invalidated_dca_ladder_is_blocked():
    decision = evaluate(armed(demo_dca_enabled=True), dca_levels=1, dca_invalidated=True)
    assert not decision.approved and DCA_INVALIDATED in decision.reasons


# ---------------------------------------------------- the full chain, again
def test_a_dca_order_still_runs_every_other_gate():
    """Section 10: a DCA order re-runs the complete RiskGate, not a shortcut."""
    decision = evaluate(armed(demo_dca_enabled=True), dca_levels=1, risk_allowed=False)
    assert not decision.approved
    assert "RiskGate" in decision.blocked_by
    assert {gate.name for gate in decision.gates} == set(chain_for().gate_names())


def test_a_dca_order_is_blocked_by_the_kill_switch():
    """The switch blocks exposure-increasing DCA as well as new entries."""
    decision = chain_for(armed(), engaged=True).evaluate(dca_order(), context(dca_levels=1))
    assert not decision.approved
    assert "DCA_BLOCKED" in decision.reasons


def test_a_dca_order_is_blocked_on_a_stale_feed():
    decision = evaluate(armed(demo_dca_enabled=True), dca_levels=1, data_age_seconds=10_000.0)
    assert not decision.approved and "DATA_STALE" in decision.reasons


def test_a_dca_order_is_blocked_when_the_daily_loss_limit_is_hit():
    from tests.phase16_helpers import daily_state

    breached = daily_state(daily_drawdown=0.05, blocked=True,
                           reasons=("MAX_DAILY_LOSS_EXCEEDED",))
    decision = evaluate(armed(demo_dca_enabled=True), dca_levels=1, daily=breached)
    assert not decision.approved
    assert "MAX_DAILY_LOSS_EXCEEDED" in decision.reasons


# --------------------------------------------------------------- no martingale
def test_dca_size_comes_from_the_sizer_not_from_a_multiplier():
    """A losing position does not buy a larger next entry: it buys a smaller one.

    Sizing is a function of the stop distance, and averaging down puts the stop
    further away from the new entry, so the derived volume shrinks.
    """
    sizer = PositionSizer(DemoRiskLimits(max_risk_per_trade=0.01, max_position_size=10.0,
                                         max_symbol_exposure=10_000_000.0,
                                         max_total_exposure=10_000_000.0))
    contract = SymbolContract("EURUSD")
    first = sizer.calculate(symbol="EURUSD", equity=10_000.0, entry_price=1.1000,
                            stop_loss=1.0950, contract=contract)
    averaged = sizer.calculate(symbol="EURUSD", equity=10_000.0, entry_price=1.0980,
                               stop_loss=1.0900, contract=contract)
    assert averaged.volume < first.volume


def test_the_service_refuses_a_dca_order_by_default(db_session):
    service, fake = service_for(db_session)
    request = dca_order()
    outcome = service.submit(request, live_context(service, request, dca_levels=1))
    assert not outcome.approved and DCA_DISABLED in outcome.reasons
    assert fake.sent == []
