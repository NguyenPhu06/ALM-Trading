"""Execution simulation: the pipeline runs, zero orders are sent."""
import inspect

import pytest

from config.settings import Settings
from observation.simulation import (
    DEMO_TRADING_DISABLED,
    ExecutionSimulator,
    ExecutionVerdict,
    KILL_SWITCH_ACTIVE,
    MT5_EXECUTION_DISABLED,
    NO_ACTIONABLE_SIGNAL,
    OBSERVATION_MODE_ACTIVE,
    RISK_BLOCKED,
    RiskVerdict,
    SignalAction,
)

BASE = dict(database_url="sqlite://", tradingview_webhook_secret="a-secure-test-secret-of-24-chars")


def simulator(**overrides):
    return ExecutionSimulator(Settings(**BASE, **overrides))


def test_a_buy_signal_is_blocked_under_the_shipped_defaults():
    result = simulator().simulate(symbol="EURUSD", signal=SignalAction.BUY)
    assert result.signal is SignalAction.BUY
    assert result.risk is RiskVerdict.APPROVED
    assert result.execution is ExecutionVerdict.BLOCKED
    assert result.primary_reason == OBSERVATION_MODE_ACTIVE
    assert result.orders_sent == 0


def test_the_summary_matches_the_documented_shape():
    summary = simulator().simulate(symbol="EURUSD", signal="BUY").summary()
    assert "SIGNAL = BUY" in summary
    assert "RISK = APPROVED" in summary
    assert "EXECUTION = BLOCKED" in summary
    assert "REASON = " in summary


def test_every_blocking_gate_is_reported():
    result = simulator().simulate(symbol="EURUSD", signal="SELL")
    assert {OBSERVATION_MODE_ACTIVE, MT5_EXECUTION_DISABLED,
            DEMO_TRADING_DISABLED, KILL_SWITCH_ACTIVE} <= set(result.reasons)


def test_a_blocked_risk_state_is_recorded():
    result = simulator().simulate(symbol="EURUSD", signal="BUY", risk_approved=False,
                                  risk_reasons=("MAX_DRAWDOWN",))
    assert result.risk is RiskVerdict.BLOCKED
    assert RISK_BLOCKED in result.reasons and "MAX_DRAWDOWN" in result.reasons


def test_failed_data_quality_is_recorded():
    result = simulator().simulate(symbol="EURUSD", signal="BUY", data_quality_ok=False)
    assert "DATA_QUALITY_FAILED" in result.reasons


def test_a_non_demo_account_is_recorded():
    result = simulator().simulate(symbol="EURUSD", signal="BUY", demo_account_valid=False)
    assert "ACCOUNT_NOT_DEMO" in result.reasons


@pytest.mark.parametrize("signal", [SignalAction.WAIT, SignalAction.HOLD])
def test_a_non_actionable_signal_needs_no_risk_verdict(signal):
    result = simulator().simulate(symbol="EURUSD", signal=signal)
    assert result.risk is RiskVerdict.NOT_REQUIRED
    assert result.execution is ExecutionVerdict.NOT_APPLICABLE
    assert result.primary_reason == NO_ACTIONABLE_SIGNAL


@pytest.mark.parametrize("signal", ["BUY", "SELL", "DCA", "EXIT"])
def test_actionable_signals_are_evaluated(signal):
    result = simulator().simulate(symbol="EURUSD", signal=signal)
    assert result.execution is ExecutionVerdict.BLOCKED


def test_even_with_every_flag_open_observation_mode_still_blocks():
    """Observation mode is the outermost guarantee of Phase 12."""
    armed = simulator(observation_mode=True, demo_trading_enabled=True,
                      mt5_execution_enabled=True, mt5_read_only=False,
                      execution_kill_switch=False)
    result = armed.simulate(symbol="EURUSD", signal="BUY")
    assert result.execution is ExecutionVerdict.BLOCKED
    assert result.reasons == (OBSERVATION_MODE_ACTIVE,)
    assert result.orders_sent == 0


def test_the_simulator_has_no_transport():
    source = inspect.getsource(ExecutionSimulator)
    for token in ("order_send", "send_market_order", "requests", "httpx", "socket"):
        assert token not in source, token
    for name in ("send", "send_order", "execute", "submit"):
        assert not hasattr(ExecutionSimulator, name), name


def test_a_simulation_always_reports_zero_orders():
    for signal in ("BUY", "SELL", "WAIT", "HOLD", "EXIT", "DCA"):
        result = simulator().simulate(symbol="EURUSD", signal=signal)
        assert result.orders_sent == 0
        assert result.as_dict()["orders_sent"] == 0


def test_hypothetical_levels_are_recorded_but_not_acted_on():
    result = simulator().simulate(symbol="EURUSD", signal="BUY", entry=1.1002,
                                  volume=0.01, sl=1.09, tp=1.11)
    payload = result.as_dict()
    assert payload["hypothetical_entry"] == 1.1002
    assert payload["hypothetical_volume"] == 0.01
    assert payload["orders_sent"] == 0
