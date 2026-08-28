"""Execution modes (sections 3 and 39).

Two properties matter more than the enum itself: OBSERVATION is what ships, and
no mode ever changes itself. A blocked gate blocks the *order* and leaves the
mode exactly where configuration put it.
"""
import pytest
from pydantic import ValidationError

from config.settings import BROKER_EXECUTION_MODES, EXECUTION_MODES, Settings
from execution.demo.modes import (
    AUTOMATION_NOT_ENABLED, BROKER_MODES, DEFAULT_MODE, LIVE_PERMANENTLY_DISABLED,
    MANUAL_APPROVAL_REQUIRED, MODE_DOES_NOT_EXECUTE, SIMULATION_MODES, ExecutionMode,
    ExecutionModeResolver, UnknownExecutionMode, parse_mode,
)
from execution.demo.gates import MODE_BLOCKS_EXECUTION
from tests.phase16_helpers import BASE, armed, chain_for, context, manual, order, settings


def resolver(**overrides):
    return ExecutionModeResolver(settings(**overrides))


# ---------------------------------------------------------------- the default
def test_observation_is_the_shipped_default():
    assert Settings(**BASE).execution_mode == "OBSERVATION"
    assert DEFAULT_MODE is ExecutionMode.OBSERVATION
    assert resolver().resolve().mode is ExecutionMode.OBSERVATION


def test_the_default_mode_sends_nothing():
    decision = resolver().resolve()
    assert decision.sends_orders is False
    assert MODE_DOES_NOT_EXECUTE in decision.reasons


def test_no_mode_enables_live_trading():
    for mode in ExecutionMode:
        config = settings(demo_execution_mode=str(mode),
                          demo_automated_execution_enabled=mode is ExecutionMode.DEMO_AUTOMATED)
        assert ExecutionModeResolver(config).resolve().live_enabled is False


# ----------------------------------------------------------------- the modes
def test_every_declared_mode_exists():
    assert {str(mode) for mode in ExecutionMode} == set(EXECUTION_MODES)


def test_only_the_two_demo_modes_reach_a_broker():
    assert {str(mode) for mode in BROKER_MODES} == set(BROKER_EXECUTION_MODES)
    assert not BROKER_MODES & SIMULATION_MODES


def test_paper_mode_does_not_execute():
    decision = resolver(demo_execution_mode="PAPER").resolve()
    assert decision.sends_orders is False
    assert MODE_DOES_NOT_EXECUTE in decision.reasons


def test_live_disabled_is_a_permanent_marker():
    decision = resolver(demo_execution_mode="LIVE_DISABLED").resolve()
    assert decision.sends_orders is False
    assert LIVE_PERMANENTLY_DISABLED in decision.reasons


def test_manual_approval_mode_requires_a_human():
    decision = ExecutionModeResolver(manual()).resolve()
    assert decision.requires_human_approval is True
    assert MANUAL_APPROVAL_REQUIRED in decision.reasons


def test_demo_automated_sends_orders_when_fully_configured():
    decision = ExecutionModeResolver(armed()).resolve()
    assert decision.mode is ExecutionMode.DEMO_AUTOMATED
    assert decision.sends_orders is True and decision.automated is True


# --------------------------------------------------------- no implicit switch
def test_an_unknown_mode_is_an_error_not_a_fallback():
    with pytest.raises(UnknownExecutionMode):
        parse_mode("DEMO_AUTOMATIC")


def test_settings_refuses_an_unknown_mode():
    with pytest.raises(ValidationError, match="DEMO_EXECUTION_MODE"):
        Settings(**BASE, demo_execution_mode="YOLO")


def test_demo_automated_needs_its_own_opt_in():
    with pytest.raises(ValidationError, match="DEMO_AUTOMATED_EXECUTION_ENABLED"):
        Settings(**BASE, demo_execution_mode="DEMO_AUTOMATED", demo_trading_enabled=True)


def test_a_broker_mode_needs_demo_trading_enabled():
    with pytest.raises(ValidationError, match="DEMO_TRADING_ENABLED"):
        Settings(**BASE, demo_execution_mode="DEMO_MANUAL_APPROVAL")


def test_a_mode_built_in_memory_without_the_opt_in_still_refuses():
    """Settings blocks this at startup; the resolver blocks it again in memory."""
    config = armed()
    object.__setattr__(config, "demo_automated_execution_enabled", False)
    decision = ExecutionModeResolver(config).resolve()
    assert decision.sends_orders is False
    assert AUTOMATION_NOT_ENABLED in decision.reasons


def test_a_blocked_gate_does_not_change_the_mode():
    """Section 3: the order is blocked, the mode is not demoted."""
    chain = chain_for(armed())
    decision = chain.evaluate(order(), context(risk_allowed=False))
    assert not decision.approved
    assert decision.mode.mode is ExecutionMode.DEMO_AUTOMATED
    assert ExecutionModeResolver(armed()).resolve().mode is ExecutionMode.DEMO_AUTOMATED


# ------------------------------------------------------------ the chain hook
def test_a_non_broker_mode_blocks_every_order():
    decision = chain_for(settings()).evaluate(order(), context())
    assert not decision.approved
    assert MODE_BLOCKS_EXECUTION in decision.reasons


def test_a_broker_mode_lets_a_clean_order_through():
    decision = chain_for(armed()).evaluate(order(), context())
    assert decision.approved and decision.reasons == ()
