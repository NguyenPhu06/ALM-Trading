from paper import PaperRiskEngine
def test_risk_rejects_exposure_spread_news_and_quality():
    r=PaperRiskEngine(max_exposure=10,max_spread=.001).evaluate(exposure=10,spread=.002,news_risk="HIGH",data_quality="INVALID",provider_status="OFFLINE")
    assert not r.allowed and {"MAXIMUM_EXPOSURE","SPREAD_TOO_WIDE","HIGH_IMPACT_EVENT_NEARBY","DATA_QUALITY_INVALID","PROVIDER_UNAVAILABLE"}<=set(r.rejection_reasons)


# ------------------------------------------------- Phase 16: hard DEMO limits
# Section 9: any limit that fails blocks the order, and a limit that cannot be
# evaluated is treated as breached rather than satisfied.
import pytest

from execution.demo.limits import (
    MAX_DAILY_LOSS, MAX_MARGIN_USAGE, MAX_OPEN_POSITIONS, MAX_POSITION_SIZE,
    MAX_RISK_PER_TRADE, MAX_SLIPPAGE, MAX_SPREAD, MAX_SYMBOL_EXPOSURE, MAX_TOTAL_DRAWDOWN,
    MAX_TOTAL_EXPOSURE, MAX_TRADES_PER_DAY, DemoRiskLimits,
)
from tests import phase16_helpers as p16


def blocked_by(**ctx):
    return p16.chain_for(p16.armed()).evaluate(
        ctx.pop("request", None) or p16.order(), p16.context(**ctx)).reasons


def test_the_shipped_limits_are_conservative():
    """Section 25: none of these was optimised on the test set, and none should be."""
    limits = DemoRiskLimits.from_config()
    assert limits.max_risk_per_trade <= 0.01
    assert limits.max_daily_loss <= 0.03
    assert limits.max_total_drawdown <= 0.10
    assert limits.max_open_positions <= 3
    assert limits.max_dca_levels <= 3
    assert limits.max_trades_per_day <= 10


def test_every_limit_is_configurable():
    limits = DemoRiskLimits.from_config({"max_risk_per_trade": 0.001, "max_open_positions": 1})
    assert limits.max_risk_per_trade == 0.001 and limits.max_open_positions == 1


def test_a_clean_request_passes_every_limit():
    assert blocked_by() == ()


def test_max_risk_per_trade_blocks():
    assert MAX_RISK_PER_TRADE in blocked_by(request=p16.order(risk_percent=0.5))


def test_max_position_size_blocks():
    assert MAX_POSITION_SIZE in blocked_by(request=p16.order(volume=0.5))


def test_max_open_positions_blocks():
    limits = DemoRiskLimits.from_config()
    assert MAX_OPEN_POSITIONS in blocked_by(open_positions=limits.max_open_positions)


def test_max_symbol_exposure_blocks():
    limits = DemoRiskLimits.from_config()
    assert MAX_SYMBOL_EXPOSURE in blocked_by(symbol_exposure=limits.max_symbol_exposure,
                                             order_notional=1.0)


def test_max_total_exposure_blocks():
    limits = DemoRiskLimits.from_config()
    assert MAX_TOTAL_EXPOSURE in blocked_by(total_exposure=limits.max_total_exposure,
                                            order_notional=1.0)


def test_max_spread_blocks():
    assert MAX_SPREAD in blocked_by(quote={"bid": 1.1000, "ask": 1.1100})


def test_max_slippage_blocks():
    assert MAX_SLIPPAGE in blocked_by(expected_slippage=0.02)


def test_max_margin_usage_blocks():
    assert MAX_MARGIN_USAGE in blocked_by(free_margin=100.0, used_margin=900.0)


def test_max_daily_loss_blocks():
    breached = p16.daily_state(daily_drawdown=0.5, blocked=True, reasons=(MAX_DAILY_LOSS,))
    assert MAX_DAILY_LOSS in blocked_by(daily=breached)


def test_max_total_drawdown_blocks():
    breached = p16.daily_state(total_drawdown=0.5, blocked=True, reasons=(MAX_TOTAL_DRAWDOWN,))
    assert MAX_TOTAL_DRAWDOWN in blocked_by(daily=breached)


def test_max_trades_per_day_blocks():
    spent = p16.daily_state(trade_count=99, blocked=True, reasons=(MAX_TRADES_PER_DAY,))
    assert MAX_TRADES_PER_DAY in blocked_by(daily=spent)


def test_an_unevaluable_risk_engine_blocks():
    assert "RISK_ENGINE_UNAVAILABLE" in blocked_by(risk_allowed=None)


def test_a_blocked_risk_engine_blocks():
    codes = blocked_by(risk_allowed=False, risk_reasons=("EXTREME_VOLATILITY",))
    assert "RISK_ENGINE_BLOCKED" in codes and "EXTREME_VOLATILITY" in codes


def test_every_failing_limit_is_reported_at_once():
    """An operator who fixes only the first reported problem is surprised twice."""
    codes = blocked_by(open_positions=99, quote={"bid": 1.1000, "ask": 1.1100},
                       risk_allowed=False)
    assert {MAX_OPEN_POSITIONS, MAX_SPREAD, "RISK_ENGINE_BLOCKED"} <= set(codes)
