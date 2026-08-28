"""Order field validation: symbol, volume, price, spread, SL and TP."""
import pytest

from execution.mt5.order_request import OrderSide, OrderType
from execution.mt5.order_result import ExecutionStatus, OrderResult, RejectionReason
from tests.phase11_helpers import context, guard_for, order


def reasons_for(request, ctx=None):
    return guard_for().evaluate(request, ctx or context()).reasons


# ---------------------------------------------------------------------- symbol
def test_an_empty_symbol_is_refused():
    assert RejectionReason.INVALID_SYMBOL in reasons_for(order(symbol="  "))


def test_a_symbol_the_broker_does_not_offer_is_refused():
    assert RejectionReason.INVALID_SYMBOL in reasons_for(order(symbol="ZZZZZZ"))


def test_a_symbol_outside_the_allowlist_is_refused():
    from tests.phase11_helpers import settings

    config = settings(armed=True, demo_execution_symbols="GBPUSD")
    decision = guard_for(config).evaluate(order(symbol="EURUSD"), context())
    assert RejectionReason.SYMBOL_NOT_ALLOWED in decision.reasons


def test_an_empty_allowlist_permits_any_known_symbol():
    assert RejectionReason.SYMBOL_NOT_ALLOWED not in reasons_for(order(symbol="EURUSD"))


# ---------------------------------------------------------------------- volume
@pytest.mark.parametrize("volume", [0.0, -0.01, -5])
def test_a_non_positive_volume_is_refused(volume):
    assert RejectionReason.INVALID_VOLUME in reasons_for(order(volume=volume))


def test_a_volume_below_the_broker_minimum_is_refused():
    assert RejectionReason.INVALID_VOLUME in reasons_for(order(volume=0.001))


def test_a_volume_above_the_configured_cap_is_refused():
    assert RejectionReason.VOLUME_ABOVE_LIMIT in reasons_for(order(volume=5.0))


def test_a_volume_off_the_lot_step_is_refused():
    """0.013 is not a tradable size on a 0.01 step."""
    assert RejectionReason.INVALID_VOLUME in reasons_for(order(volume=0.013))


@pytest.mark.parametrize("volume", [0.01, 0.02, 0.10])
def test_valid_lot_sizes_pass(volume):
    codes = reasons_for(order(volume=volume))
    assert RejectionReason.INVALID_VOLUME not in codes
    assert RejectionReason.VOLUME_ABOVE_LIMIT not in codes


def test_a_nan_volume_is_refused():
    assert RejectionReason.INVALID_VOLUME in reasons_for(order(volume=float("nan")))


# ----------------------------------------------------------------------- price
def test_a_non_positive_price_is_refused():
    assert RejectionReason.INVALID_PRICE in reasons_for(order(price=-1.0))


def test_a_price_far_from_the_market_is_refused():
    assert RejectionReason.PRICE_DEVIATION in reasons_for(order(price=1.5))


def test_a_price_close_to_the_market_passes():
    assert RejectionReason.PRICE_DEVIATION not in reasons_for(order(price=1.10030))


def test_an_inverted_quote_is_refused():
    codes = reasons_for(order(), context(quote={"bid": 1.20, "ask": 1.10}))
    assert RejectionReason.INVALID_PRICE in codes


def test_omitting_the_price_is_allowed_for_a_market_order():
    assert RejectionReason.INVALID_PRICE not in reasons_for(order(price=None))


# ------------------------------------------------------------------ stop levels
def test_a_buy_stop_loss_above_entry_is_refused():
    assert RejectionReason.INVALID_STOP_LOSS in reasons_for(order(side=OrderSide.BUY, sl=1.20))


def test_a_buy_take_profit_below_entry_is_refused():
    assert RejectionReason.INVALID_TAKE_PROFIT in reasons_for(order(side=OrderSide.BUY, tp=1.05))


def test_a_sell_stop_loss_below_entry_is_refused():
    assert RejectionReason.INVALID_STOP_LOSS in reasons_for(
        order(side=OrderSide.SELL, sl=1.05, tp=1.09))


def test_a_sell_take_profit_above_entry_is_refused():
    assert RejectionReason.INVALID_TAKE_PROFIT in reasons_for(
        order(side=OrderSide.SELL, sl=1.11, tp=1.20))


def test_a_stop_too_close_to_entry_is_refused():
    assert RejectionReason.INVALID_STOP_LOSS in reasons_for(order(sl=1.10020))


def test_correctly_placed_sell_stops_pass():
    codes = reasons_for(order(side=OrderSide.SELL, sl=1.11000, tp=1.09000))
    assert RejectionReason.INVALID_STOP_LOSS not in codes
    assert RejectionReason.INVALID_TAKE_PROFIT not in codes


def test_omitting_stops_is_allowed():
    codes = reasons_for(order(sl=None, tp=None))
    assert RejectionReason.INVALID_STOP_LOSS not in codes
    assert RejectionReason.INVALID_TAKE_PROFIT not in codes


# ---------------------------------------------------------------------- result
def test_a_blocked_result_carries_every_reason_and_no_ticket():
    request = order()
    result = OrderResult.blocked_by(request, (RejectionReason.KILL_SWITCH_ENGAGED,
                                              RejectionReason.RISK_BLOCKED))
    assert result.status is ExecutionStatus.BLOCKED and result.blocked
    assert not result.accepted and result.broker_ticket is None
    assert result.error_code == "KILL_SWITCH_ENGAGED"
    assert set(result.reasons) == {"KILL_SWITCH_ENGAGED", "RISK_BLOCKED"}


def test_a_request_is_inert_until_a_guard_approves_it():
    """Constructing an OrderRequest must have no side effect at all."""
    request = order()
    assert request.order_type is OrderType.MARKET
    assert not hasattr(request, "send") and not hasattr(request, "execute")


# ------------------------------------------- Phase 16: the strict DEMO contract
# The Phase 11 guard still owns symbol, volume, price and stop validation; these
# tests cover what Phase 16 added on top of it (section 7).
from execution.demo.gates import VOLUME_NOT_SIZED
from execution.demo.limits import MAX_POSITION_SIZE, MAX_RISK_PER_TRADE
from execution.demo.order import DemoOrderRequest
from tests import phase16_helpers as p16


def demo_reasons(request=None, **ctx):
    return p16.chain_for(p16.armed()).evaluate(request or p16.order(), p16.context(**ctx)).reasons


def test_the_demo_contract_carries_the_whole_provenance():
    """Section 6, field for field."""
    payload = p16.order().as_dict()
    for name in ("request_id", "symbol", "side", "volume", "order_type", "price", "stop_loss",
                 "take_profit", "strategy_id", "strategy_version", "model_version",
                 "feature_version", "signal_id", "risk_snapshot_id", "timestamp", "reason"):
        assert name in payload


def test_the_demo_contract_is_inert():
    request = p16.order()
    assert not hasattr(request, "send") and not hasattr(request, "execute")
    assert not hasattr(request, "submit")


def test_a_zero_volume_order_is_refused():
    assert VOLUME_NOT_SIZED in demo_reasons(p16.order(volume=0.0))


def test_a_volume_above_the_position_limit_is_refused():
    assert MAX_POSITION_SIZE in demo_reasons(p16.order(volume=0.5))


def test_a_risk_percent_above_the_limit_is_refused():
    assert MAX_RISK_PER_TRADE in demo_reasons(p16.order(risk_percent=0.5))


def test_a_risk_amount_above_the_equity_budget_is_refused():
    assert MAX_RISK_PER_TRADE in demo_reasons(p16.order(risk_amount=5_000.0), equity=10_000.0)


def test_an_unknown_symbol_is_refused_by_the_chain():
    assert RejectionReason.INVALID_SYMBOL in demo_reasons(p16.order(symbol="ZZZZZZ"))


def test_a_broken_lot_step_is_refused_by_the_chain():
    assert RejectionReason.INVALID_VOLUME in demo_reasons(p16.order(volume=0.013))


def test_a_missing_quote_blocks_both_the_spread_gate_and_the_guard():
    codes = demo_reasons(quote=None)
    assert "SPREAD_UNAVAILABLE" in codes
    assert RejectionReason.QUOTE_UNAVAILABLE in codes


def test_a_wide_spread_is_refused():
    assert "MAX_SPREAD_EXCEEDED" in demo_reasons(quote={"bid": 1.1000, "ask": 1.1100})


def test_excess_expected_slippage_is_refused():
    assert "MAX_SLIPPAGE_EXCEEDED" in demo_reasons(expected_slippage=0.01)


def test_stale_data_is_refused():
    assert "DATA_STALE" in demo_reasons(data_age_seconds=100_000.0)


def test_unknown_data_quality_is_refused():
    """Unknown is never treated as good."""
    assert "DATA_QUALITY_UNKNOWN" in demo_reasons(data_quality_ok=None, data_quality=None)


def test_a_failing_timeframe_is_refused():
    failing = {"M5": {"verdict": "FAIL", "reasons": ["STALE_DATA"]}}
    assert "DATA_QUALITY_FAILED" in demo_reasons(data_quality=failing, data_quality_ok=None)


def test_no_order_bypasses_validation():
    """Every gate in the section 5 list runs on every request."""
    decision = p16.chain_for(p16.armed()).evaluate(p16.order(), p16.context())
    assert {gate.name for gate in decision.gates} == set(p16.chain_for().gate_names())
