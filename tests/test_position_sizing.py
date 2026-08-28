"""Position sizing (section 8).

The rule the whole file is about: there is no arbitrary lot size. Volume comes
from equity, risk, stop distance and tick economics, and when any of those is
missing the answer is a refusal with a reason, not a default.
"""
import pytest

from execution.demo.limits import DemoRiskLimits
from execution.demo.sizing import (
    BELOW_MINIMUM_VOLUME, CAPPED_BY_MARGIN, CAPPED_BY_MAX_POSITION_SIZE,
    CAPPED_BY_SYMBOL_EXPOSURE, CAPPED_BY_TOTAL_EXPOSURE, INVALID_RISK_PERCENT, NO_EQUITY,
    NO_STOP_DISTANCE, NO_TICK_ECONOMICS, RISK_PERCENT_ABOVE_LIMIT, PositionSizer,
    SymbolContract,
)

# Wide enough limits that only the mechanism under test binds.
OPEN = DemoRiskLimits(max_risk_per_trade=0.01, max_position_size=10.0,
                      max_symbol_exposure=10_000_000.0, max_total_exposure=10_000_000.0,
                      min_volume=0.01, volume_step=0.01, min_stop_distance=0.0005)
EURUSD = SymbolContract("EURUSD", tick_size=0.00001, tick_value=1.0, contract_size=100_000.0,
                        volume_min=0.01, volume_max=100.0, volume_step=0.01)


def size(**overrides):
    limits = overrides.pop("limits", OPEN)
    payload = dict(symbol="EURUSD", equity=10_000.0, entry_price=1.10, stop_loss=1.09,
                   contract=EURUSD)
    payload.update(overrides)
    return PositionSizer(limits).calculate(**payload)


# ------------------------------------------------------------- the arithmetic
def test_volume_comes_from_risk_stop_distance_and_tick_value():
    """1% of 10,000 is 100; a 0.01 stop is 1000 ticks at 1.0 per tick, so 0.10 lots."""
    result = size()
    assert result.risk_amount == pytest.approx(100.0)
    assert result.stop_distance == pytest.approx(0.01)
    assert result.volume == pytest.approx(0.10)


def test_a_wider_stop_produces_a_smaller_position():
    tight = size(stop_loss=1.095).volume
    wide = size(stop_loss=1.08).volume
    assert wide < tight


def test_more_equity_produces_a_larger_position():
    assert size(equity=20_000.0).volume > size(equity=10_000.0).volume


def test_the_symbol_contract_changes_the_answer():
    """Gold is not EURUSD: same risk, different tick economics, different lots."""
    gold = SymbolContract("XAUUSD", tick_size=0.01, tick_value=1.0, contract_size=100.0,
                          volume_min=0.01, volume_max=50.0, volume_step=0.01)
    result = size(symbol="XAUUSD", entry_price=2400.0, stop_loss=2380.0, contract=gold)
    # 100 risk / (2000 ticks * 1.0) = 0.05 lots.
    assert result.volume == pytest.approx(0.05)


def test_the_volume_is_floored_to_the_broker_step():
    stepped = SymbolContract("EURUSD", volume_step=0.10, volume_min=0.10)
    result = size(contract=stepped)
    assert result.volume == pytest.approx(0.10)
    assert result.raw_volume == pytest.approx(0.10)


# ------------------------------------------------------------- the refusals
def test_no_stop_loss_means_no_position():
    result = size(stop_loss=None)
    assert not result.valid and NO_STOP_DISTANCE in result.reasons


def test_a_stop_at_the_entry_means_no_position():
    result = size(stop_loss=1.10)
    assert not result.valid and NO_STOP_DISTANCE in result.reasons


def test_a_stop_inside_the_minimum_distance_means_no_position():
    result = size(stop_loss=1.09999)
    assert not result.valid and NO_STOP_DISTANCE in result.reasons


def test_no_equity_means_no_position():
    result = size(equity=0.0)
    assert not result.valid and NO_EQUITY in result.reasons


def test_missing_tick_economics_means_no_position():
    broken = SymbolContract("EURUSD", tick_size=0.0, tick_value=0.0)
    result = size(contract=broken)
    assert not result.valid and NO_TICK_ECONOMICS in result.reasons


def test_a_non_positive_risk_percent_is_refused():
    result = size(risk_percent=0.0)
    assert not result.valid and INVALID_RISK_PERCENT in result.reasons


def test_a_risk_budget_too_small_for_one_lot_is_refused():
    """Trading the minimum anyway would exceed the configured risk."""
    result = size(equity=50.0)
    assert not result.valid and BELOW_MINIMUM_VOLUME in result.reasons


# ----------------------------------------------------------------- the caps
def test_a_caller_cannot_ask_for_more_risk_than_the_limit():
    result = size(risk_percent=0.50)
    assert RISK_PERCENT_ABOVE_LIMIT in result.reasons
    assert result.risk_percent == OPEN.max_risk_per_trade


def test_max_position_size_caps_the_volume():
    limits = DemoRiskLimits(max_risk_per_trade=0.05, max_position_size=0.02,
                            max_symbol_exposure=10_000_000.0, max_total_exposure=10_000_000.0)
    result = size(limits=limits, equity=100_000.0)
    assert result.volume == pytest.approx(0.02)
    assert CAPPED_BY_MAX_POSITION_SIZE in result.reasons


def test_symbol_exposure_caps_the_volume():
    limits = DemoRiskLimits(max_risk_per_trade=0.01, max_position_size=10.0,
                            max_symbol_exposure=8_800.0, max_total_exposure=10_000_000.0)
    result = size(limits=limits)
    # Risk alone allowed 0.10; 8,800 of room at 110,000 per lot allows only 0.08.
    assert result.volume == pytest.approx(0.08)
    assert CAPPED_BY_SYMBOL_EXPOSURE in result.reasons


def test_existing_exposure_reduces_the_room():
    limits = DemoRiskLimits(max_risk_per_trade=0.01, max_position_size=10.0,
                            max_symbol_exposure=11_000.0, max_total_exposure=10_000_000.0)
    result = size(limits=limits, open_symbol_exposure=5_500.0)
    assert result.volume == pytest.approx(0.05)


def test_total_exposure_caps_the_volume():
    limits = DemoRiskLimits(max_risk_per_trade=0.01, max_position_size=10.0,
                            max_symbol_exposure=10_000_000.0, max_total_exposure=5_500.0)
    result = size(limits=limits)
    assert result.volume == pytest.approx(0.05)
    assert CAPPED_BY_TOTAL_EXPOSURE in result.reasons


def test_margin_usage_caps_the_volume():
    limits = DemoRiskLimits(max_risk_per_trade=0.01, max_position_size=10.0,
                            max_symbol_exposure=10_000_000.0, max_total_exposure=10_000_000.0,
                            max_margin_usage=0.30)
    result = size(limits=limits, free_margin=1_000.0, margin_per_lot=5_000.0)
    # 30% of 1,000 is 300; at 5,000 margin per lot that is 0.06 lots.
    assert result.volume == pytest.approx(0.06)
    assert CAPPED_BY_MARGIN in result.reasons


# ------------------------------------------------------------ the contract
def test_the_contract_prefers_what_the_terminal_reports():
    info = {"trade_tick_size": 0.001, "trade_tick_value": 0.5, "trade_contract_size": 1_000.0,
            "volume_min": 0.05, "volume_max": 7.0, "volume_step": 0.05, "digits": 3}
    contract = SymbolContract.from_symbol_info("EURUSD", info)
    assert contract.tick_size == 0.001 and contract.tick_value == 0.5
    assert contract.volume_step == 0.05 and contract.digits == 3


def test_the_contract_falls_back_to_configuration_per_field():
    contract = SymbolContract.from_symbol_info("EURUSD", {"volume_step": 0.05})
    assert contract.volume_step == 0.05
    assert contract.contract_size == 100_000.0, "unreported fields come from configuration"


def test_the_configured_gold_contract_differs_from_the_default():
    assert SymbolContract.from_config("XAUUSD").contract_size == 100.0
    assert SymbolContract.from_config("EURUSD").contract_size == 100_000.0
