"""Phase 12 mandatory safety matrix (section 25).

Every case asserts both that the pipeline stopped or blocked AND that no order
was sent. A block that still transmitted would be worthless.
"""
import ast
import inspect
import pathlib

import pytest

from config.settings import get_settings
from observation.cycle import CycleStage, ObservationCycle
from observation.simulation import ExecutionVerdict, SignalAction
from tests.phase12_helpers import NOW, REAL_TRADE_MODE, client as mt5_client, cycle_for, module
from tests.phase9_helpers import StubInference

FORBIDDEN_CALLS = ("order_send", "send_market_order", "order_check", "position_close")


# ----------------------------------------------------------------- 25. BLOCK
def test_real_account_blocks(db_session):
    cycle = cycle_for(db_session, mt5=mt5_client(trade_mode=REAL_TRADE_MODE))
    result = cycle.run("EURUSD")
    assert result.halted and result.stage == CycleStage.ACCOUNT
    assert "ACCOUNT_IS_REAL" in result.reasons
    assert result.orders_sent == 0


def test_unknown_account_blocks(db_session):
    """A server that cannot be verified as DEMO stops the cycle."""
    cycle = cycle_for(db_session, mt5=mt5_client(server="Unverified-99"))
    result = cycle.run("EURUSD")
    assert result.halted and result.orders_sent == 0


def test_mt5_disconnected_blocks(db_session):
    cycle = cycle_for(db_session, mt5=mt5_client(connected=False))
    result = cycle.run("EURUSD")
    assert result.halted and result.stage == CycleStage.ACCOUNT
    assert result.orders_sent == 0


def test_no_market_data_blocks(db_session):
    connected = mt5_client()
    connected.fake.symbol_names = ()
    result = cycle_for(db_session, mt5=connected).run("EURUSD")
    assert result.halted and result.stage == CycleStage.MARKET_DATA
    assert result.orders_sent == 0


def test_bad_data_blocks_before_any_signal(db_session):
    """A failing quality gate must stop the cycle before a signal is produced."""
    from observation.quality_gate import DataQualityGate

    cycle = cycle_for(db_session, inference=StubInference())
    cycle.gate = DataQualityGate(minimum_candles=100_000)
    result = cycle.run("EURUSD")
    assert result.halted and result.stage == CycleStage.DATA_QUALITY
    assert "DATA_QUALITY_FAILED" in result.reasons
    assert result.simulation is None and result.orders_sent == 0


def test_nn_failure_does_not_produce_an_order(db_session):
    class Exploding:
        def predict(self, snapshot):
            raise RuntimeError("model failure")

    result = cycle_for(db_session, inference=Exploding()).run("EURUSD")
    assert result.orders_sent == 0
    assert result.simulation.execution is not ExecutionVerdict.SIMULATED


def test_risk_failure_is_recorded_and_blocks(db_session):
    result = cycle_for(db_session, inference=None).run("EURUSD")
    simulation = result.simulation
    assert simulation.execution is ExecutionVerdict.BLOCKED
    assert result.orders_sent == 0


def test_kill_switch_and_execution_disabled_both_block(db_session):
    result = cycle_for(db_session, inference=StubInference()).run("EURUSD")
    reasons = set(result.simulation.reasons)
    assert "KILL_SWITCH_ACTIVE" in reasons
    assert "MT5_EXECUTION_DISABLED" in reasons
    assert "DEMO_TRADING_DISABLED" in reasons
    assert result.orders_sent == 0


def test_a_strategy_signal_only_ever_produces_a_simulation(db_session):
    result = cycle_for(db_session, inference=StubInference()).run("EURUSD")
    assert result.simulation is not None
    assert result.simulation.execution is ExecutionVerdict.BLOCKED
    assert result.simulation.orders_sent == 0


# ------------------------------------------------------- 26. default posture
def test_the_shipped_defaults_permit_no_trading():
    settings = get_settings()
    assert settings.observation_mode is True
    assert settings.demo_trading_enabled is False
    assert settings.mt5_execution_enabled is False
    assert settings.execution_kill_switch is True
    assert settings.live_trading_enabled is False
    assert settings.environment == "DEMO"


# ------------------------------------------------- no order path in the package
def test_no_observation_module_calls_an_execution_function():
    offenders = []
    for path in pathlib.Path("observation").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CALLS:
                offenders.append(f"{path.name}:{node.attr}")
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_CALLS:
                offenders.append(f"{path.name}:{node.id}")
    assert offenders == [], offenders


def test_the_observation_cycle_imports_no_execution_client():
    source = inspect.getsource(ObservationCycle)
    for token in ("MT5ExecutionClient", "DemoExecutionService", "send_market_order",
                  "PaperTradingService"):
        assert token not in source, token


def test_the_cycle_exposes_no_execution_collaborator(db_session):
    cycle = cycle_for(db_session)
    for name in ("execution_client", "broker", "paper", "send_order"):
        assert not hasattr(cycle, name), name


def test_no_test_in_this_module_can_send_an_order(db_session):
    """The fake read-only terminal has no order_send at all."""
    connected = mt5_client()
    assert not hasattr(connected.fake, "order_send")
