"""Strategy consumes NN output; the NN never bypasses anything (sections 1, 32, 38, 40).

The architecture must hold in this order:

    ... -> Neural Network -> Strategy Engine -> Risk Engine -> Execution Guard

The NN provides probabilities. It must never reach the Strategy Engine's verdict,
the Risk Engine, the Execution Guard or the kill switch on its own.
"""
import ast
import inspect
import pathlib

import pytest

from ai.inference.multitask_engine import ConfidenceThresholds, MultiTaskInferenceEngine
from ai.model_registry import ModelRegistry
from ai.models.multitask import MultiTaskMLP
from ai.training.forward_trainer import ForwardTrainer
from config.settings import get_settings
from execution.mt5.execution_guard import ExecutionGuard
from observation.simulation import ExecutionVerdict
from strategy.engine import StrategyIntelligenceEngine

AI_PACKAGE = pathlib.Path("ai")
FORBIDDEN_IN_AI = (
    "MT5ExecutionClient", "DemoExecutionService", "send_market_order", "order_send",
    "ExecutionGuard", "ExecutionKillSwitch", "PaperTradingService",
)


def identifiers(source: str) -> set[str]:
    tree = ast.parse(source)
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
    return names


# ---------------------------------------------------- 1. architectural boundary
def test_no_ai_module_references_execution():
    offenders = []
    for path in AI_PACKAGE.rglob("*.py"):
        names = identifiers(path.read_text(encoding="utf-8"))
        for symbol in FORBIDDEN_IN_AI:
            if symbol in names or any(name.endswith(f".{symbol}") for name in names):
                offenders.append(f"{path.as_posix()}:{symbol}")
        offenders.extend(f"{path.as_posix()}:{name}" for name in names
                         if "execution.mt5" in name)
    assert offenders == [], offenders


def test_the_strategy_engine_still_owns_the_decision():
    source = inspect.getsource(StrategyIntelligenceEngine)
    assert "prediction" in source, "the strategy must consume the NN output"
    # The NN contributes one weighted component, not the verdict.
    assert "nn_alignment" in source


def test_the_nn_is_one_weighted_component_not_the_authority():
    from strategy.scoring import DEFAULT_WEIGHTS

    assert "nn_alignment" in DEFAULT_WEIGHTS
    assert DEFAULT_WEIGHTS["nn_alignment"] < 0.5, "the NN must not dominate the score"
    assert DEFAULT_WEIGHTS["nn_alignment"] <= DEFAULT_WEIGHTS["structure_alignment"]


def test_a_missing_model_never_produces_an_entry(db_session):
    """Preserved from earlier phases: no model means no trade."""
    from tests.phase12_helpers import cycle_for

    result = cycle_for(db_session, inference=None).run("EURUSD")
    assert result.snapshot.neural_network is None
    assert str(result.signal) not in {"BUY", "SELL"}


def test_a_confident_model_still_passes_through_strategy_and_risk(db_session):
    from tests.phase9_helpers import StubInference
    from tests.phase12_helpers import cycle_for

    result = cycle_for(db_session, inference=StubInference(prob_up=0.95, prob_down=0.03,
                                                          prob_neutral=0.02)).run("EURUSD")
    # Even at 95% confidence the execution stage is still a blocked simulation.
    assert result.simulation.execution is ExecutionVerdict.BLOCKED
    assert result.orders_sent == 0
    assert result.snapshot.strategy, "the strategy still produced the decision"


def test_the_inference_engine_cannot_reach_the_execution_guard():
    source = inspect.getsource(MultiTaskInferenceEngine)
    for token in ("ExecutionGuard", "send_market_order", "order_send", "kill_switch"):
        assert token not in source, token


def test_threshold_verdicts_are_advisory_not_authoritative():
    from ai.models.multitask import MultiTaskOutput

    names = ("trend_m15",)
    engine = MultiTaskInferenceEngine(
        MultiTaskMLP(1), feature_names=names, means={"trend_m15": 0.0},
        deviations={"trend_m15": 1.0}, model_version="v1", feature_version="features_v1")
    output = MultiTaskOutput({"UP": 0.99, "DOWN": 0.005, "NEUTRAL": 0.005}, 0.01, 0.02,
                             -0.001, 0.5, 0.99)
    meets, _ = engine.evaluate_thresholds(output)
    assert meets
    # Meeting the bar is not an order, and the engine cannot send one.
    for name in ("send", "execute", "submit", "order"):
        assert not hasattr(engine, name), name


# ------------------------------------------------------- 40. critical safety
def test_training_cannot_place_an_order_or_change_the_environment(db_session):
    """Training must not trade, touch MT5, enable execution or move the kill switch."""
    from ai.models.multitask import MultiTaskConfig
    from tests.phase13_helpers import build_dataset

    settings = get_settings()
    before = {
        "live": settings.live_trading_enabled,
        "demo": settings.demo_trading_enabled,
        "mt5_execution": settings.mt5_execution_enabled,
        "kill_switch": settings.execution_kill_switch,
        "environment": settings.trading_environment,
        "observation": settings.observation_mode,
    }

    report = ForwardTrainer(config=MultiTaskConfig(epochs=20, hidden_units=8)).train(
        build_dataset(count=300))
    assert report.model_id

    after = get_settings()
    assert after.live_trading_enabled == before["live"] is False
    assert after.demo_trading_enabled == before["demo"] is False
    assert after.mt5_execution_enabled == before["mt5_execution"] is False
    assert after.execution_kill_switch == before["kill_switch"] is True
    assert after.trading_environment == before["environment"] == "DEMO"
    assert after.observation_mode == before["observation"] is True


def test_the_trainer_touches_no_broker_or_execution_object():
    source = inspect.getsource(ForwardTrainer)
    for token in ("mt5", "broker", "order", "execution_guard", "kill_switch",
                  "PaperTradingService"):
        assert token not in source.lower() or token == "order", token
    names = identifiers(inspect.getsource(ForwardTrainer))
    assert not [name for name in names if "execution.mt5" in name]


def test_promotion_cannot_enable_execution(db_session, tmp_path):
    from ai.model_registry import ApprovalToken, ModelState
    from tests.phase13_helpers import model_record

    settings = get_settings()
    registry = ModelRegistry(artifacts_path=str(tmp_path))
    registry.register(model_record("safety-1"))
    registry.transition("safety-1", ModelState.VALIDATED)
    registry.promote("safety-1", ApprovalToken("nvphu", "safety check"), force=True)

    after = get_settings()
    assert after.mt5_execution_enabled is False
    assert after.demo_trading_enabled is False
    assert after.execution_kill_switch is True
    assert after.live_trading_enabled is False


def test_the_shipped_defaults_are_unchanged_by_phase_13():
    settings = get_settings()
    assert settings.live_trading_enabled is False
    assert settings.demo_trading_enabled is False
    assert settings.mt5_execution_enabled is False
    assert settings.execution_kill_switch is True
    assert settings.observation_mode is True
    assert settings.ai_auto_promote is False
    assert settings.ai_online_learning_enabled is False


def test_online_learning_is_structurally_disabled():
    """No fit() may be reachable from the observation loop (section 30)."""
    from observation.cycle import ObservationCycle

    source = inspect.getsource(ObservationCycle)
    for token in (".fit(", "ForwardTrainer", "MultiTaskMLP", "train("):
        assert token not in source, token


def test_no_api_endpoint_trains_a_model():
    from api.main import app

    writes = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
              for route in app.routes
              if route.path.startswith("/ai") and getattr(route, "methods", None)
              and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert writes == {"POST /ai/retraining/request", "POST /ai/models/{model_id}/approve"}
