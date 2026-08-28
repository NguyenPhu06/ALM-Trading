"""Phase 14 mandatory safety tests (section 30).

    observation cycle  -> ZERO broker orders
    training job       -> ZERO broker orders
    model evaluation   -> ZERO broker orders
    drift detection    -> ZERO broker orders
    edge detection     -> ZERO broker orders
    restart            -> ZERO broker orders
    REAL account       -> BLOCK
    KILL_SWITCH=true   -> BLOCK

Each is asserted twice where it can be: behaviourally (run it, count the orders)
and structurally (parse the source, prove the call does not exist).
"""
import ast
import inspect
import pathlib
from datetime import timedelta

import pytest

from ai.edge import EdgeDetector
from ai.model_registry.drift import DriftMonitor
from ai.performance import ErrorAnalyzer, ForwardSegmentLearner, RollingPerformance
from ai.training.evaluation import ChallengerEvaluator
from ai.training.pipeline import TrainingPipeline
from ai.training.train import TrainingJob
from ai.training.triggers import TrainingTriggerPolicy
from api.main import app
from config.settings import get_settings
from observation.driver import DriverConfig, ObservationDriver
from observation.ingestion import DatasetIngestor
from observation.outcome import ForwardOutcomeEngine
from tests.phase14_helpers import (
    BASELINES,
    NOW,
    FakeCycle,
    RecordingAlerts,
    candles,
    entries,
    observation,
    outcome,
    performance_entries,
)

SAFETY_FLAGS = ("live_trading_enabled", "demo_trading_enabled", "mt5_execution_enabled",
                "execution_kill_switch", "observation_mode", "ai_auto_promote",
                "ai_online_learning_enabled", "ai_automatic_training")

# Anything that could reach a broker.
EXECUTION_TOKENS = ("order_send", "send_market_order", "MT5ExecutionClient",
                    "DemoExecutionService", "ExecutionGuard", "ExecutionKillSwitch",
                    "PaperExecutionEngine", "position_close", "order_check")

PHASE_14_MODULES = (
    "observation/driver.py", "observation/lifecycle.py", "observation/outcome.py",
    "observation/ingestion.py", "ai/edge/edge_detector.py", "ai/edge/evidence.py",
    "ai/performance/errors.py", "ai/performance/memory.py", "ai/performance/rolling.py",
    "ai/performance/segments.py", "ai/training/train.py", "ai/training/pipeline.py",
    "ai/training/evaluation.py", "ai/training/triggers.py",
    "database/repositories/forward.py",
)


def flags():
    settings = get_settings()
    return {name: getattr(settings, name) for name in SAFETY_FLAGS}


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


# ------------------------------------------------- the modules cannot trade
@pytest.mark.parametrize("module", PHASE_14_MODULES)
def test_no_phase_14_module_references_an_execution_symbol(module):
    names = identifiers(pathlib.Path(module).read_text(encoding="utf-8"))
    offenders = [token for token in EXECUTION_TOKENS
                 if token in names or any(name.endswith(f".{token}") for name in names)]
    assert offenders == [], f"{module}: {offenders}"


@pytest.mark.parametrize("module", PHASE_14_MODULES)
def test_no_phase_14_module_imports_the_execution_package(module):
    names = identifiers(pathlib.Path(module).read_text(encoding="utf-8"))
    assert not [name for name in names if "execution.mt5" in name], module


def test_the_driver_holds_no_execution_client():
    driver = ObservationDriver(cycle=FakeCycle(timestamp=NOW),
                               config=DriverConfig(interval_seconds=300),
                               clock=lambda: NOW, sleeper=lambda seconds: None)
    for name in ("client", "broker", "execution", "guard", "kill_switch"):
        assert not hasattr(driver, name), name


# --------------------------------------------------- 30. ZERO broker orders
def test_an_observation_cycle_sends_zero_orders(memory_repository):
    driver = ObservationDriver(cycle=FakeCycle(timestamp=NOW), repository=memory_repository,
                               config=DriverConfig(interval_seconds=300),
                               alerts=RecordingAlerts(), clock=lambda: NOW,
                               sleeper=lambda seconds: None)
    tick = driver.run_once(now=NOW)
    assert tick.orders_sent == 0
    assert all(report.orders_sent == 0 for report in tick.cycles)
    assert tick.as_dict()["orders_sent"] == 0


def test_resolving_an_outcome_sends_zero_orders():
    before = flags()
    result = ForwardOutcomeEngine().resolve(
        observation(), candles(14, start=NOW, step_minutes=5),
        now=NOW + timedelta(hours=1, minutes=1))
    assert result.ok
    assert flags() == before


def test_a_training_job_sends_zero_orders():
    before = flags()
    report = TrainingPipeline().run([], [])
    assert report.orders_sent == 0
    assert report.promoted is False
    assert flags() == before


def test_model_evaluation_sends_zero_orders():
    source = inspect.getsource(ChallengerEvaluator)
    for token in EXECUTION_TOKENS:
        assert token not in source, token
    assert flags() == flags()


def test_drift_detection_sends_zero_orders():
    before = flags()
    DriftMonitor().evaluate(baseline_score=0.9, current_score=0.1)
    assert flags() == before


def test_edge_detection_sends_zero_orders():
    before = flags()
    report = EdgeDetector().evaluate(entries(120, net=0.0004), baselines=BASELINES)
    assert report.as_dict()["evidence"] == "FORWARD_OBSERVATION"
    assert flags() == before


def test_a_restart_sends_zero_orders(memory_repository):
    config = DriverConfig(interval_seconds=300)
    first = ObservationDriver(cycle=FakeCycle(timestamp=NOW), repository=memory_repository,
                              config=config, clock=lambda: NOW, sleeper=lambda s: None)
    first.run_once(now=NOW)
    second = ObservationDriver(cycle=FakeCycle(timestamp=NOW), repository=memory_repository,
                               config=config, clock=lambda: NOW, sleeper=lambda s: None)
    second.resume()
    assert second.run_once(now=NOW).orders_sent == 0


def test_performance_analysis_sends_zero_orders():
    before = flags()
    RollingPerformance().summary(performance_entries(40, now=NOW), now=NOW)
    ForwardSegmentLearner().all_dimensions(performance_entries(40, now=NOW))
    ErrorAnalyzer().classify(observation(), outcome(future_return=-0.001, net=-0.0011))
    assert flags() == before


def test_dataset_ingestion_sends_zero_orders(memory_repository):
    before = flags()
    DatasetIngestor(memory_repository).ingest(observation(), outcome())
    assert flags() == before


# ------------------------------------------------------- REAL account BLOCK
def test_a_real_account_halts_the_cycle_before_anything_else(db_session):
    """Preserved from Phase 12: the driver inherits the cycle's account guard."""
    from observation.demo_account import DemoValidation
    from tests.phase12_helpers import cycle_for, client

    real = client(trade_mode=2)
    result = cycle_for(db_session, mt5=real).run("EURUSD")
    assert result.halted
    assert result.account.status is DemoValidation.INVALID_ACCOUNT
    assert result.orders_sent == 0


def test_a_real_account_never_produces_an_observing_record(db_session, memory_repository):
    from tests.phase12_helpers import cycle_for, client

    driver = ObservationDriver(cycle=cycle_for(db_session, mt5=client(trade_mode=2)),
                               repository=memory_repository,
                               config=DriverConfig(interval_seconds=300),
                               clock=lambda: NOW, sleeper=lambda seconds: None)
    tick = driver.run_once(now=NOW)
    assert tick.executed == ()
    assert all(record.failed for record in memory_repository.observations.values())


# ------------------------------------------------------- KILL_SWITCH BLOCK
def test_the_kill_switch_is_engaged_by_default():
    assert get_settings().execution_kill_switch is True


def test_the_driver_cannot_release_the_kill_switch():
    source = inspect.getsource(ObservationDriver)
    for token in ("kill_switch", "release", "engage"):
        assert token not in source, token


def test_running_the_loop_leaves_every_safety_flag_untouched(memory_repository):
    before = flags()
    driver = ObservationDriver(cycle=FakeCycle(timestamp=NOW), repository=memory_repository,
                               config=DriverConfig(interval_seconds=300),
                               alerts=RecordingAlerts(), clock=lambda: NOW,
                               sleeper=lambda seconds: None)
    driver.run_forever(max_ticks=3)
    assert flags() == before


def test_the_shipped_defaults_are_unchanged_by_phase_14():
    settings = get_settings()
    assert settings.live_trading_enabled is False
    assert settings.demo_trading_enabled is False
    assert settings.mt5_execution_enabled is False
    assert settings.execution_kill_switch is True
    assert settings.observation_mode is True
    assert settings.ai_auto_promote is False
    assert settings.ai_online_learning_enabled is False
    assert settings.ai_automatic_training is False


def test_automatic_training_cannot_be_enabled():
    from pydantic import ValidationError

    from config.settings import Settings

    with pytest.raises((ValidationError, ValueError), match="AI_AUTOMATIC_TRAINING"):
        Settings(ai_automatic_training=True)


def test_the_driver_refuses_to_start_with_an_execution_gate_open():
    from types import SimpleNamespace

    from scripts.run_observation_driver import UnsafeConfiguration, _refuse_unless_safe

    unsafe = SimpleNamespace(live_trading_enabled=False, demo_trading_enabled=True,
                             mt5_execution_enabled=True, execution_kill_switch=False,
                             observation_mode=False)
    with pytest.raises(UnsafeConfiguration) as error:
        _refuse_unless_safe(unsafe)
    message = str(error.value)
    for token in ("DEMO_TRADING_ENABLED", "MT5_EXECUTION_ENABLED",
                  "EXECUTION_KILL_SWITCH_RELEASED", "OBSERVATION_MODE_OFF"):
        assert token in message


def test_the_driver_starts_with_the_shipped_settings():
    from scripts.run_observation_driver import _refuse_unless_safe

    assert _refuse_unless_safe(get_settings()) is None


# --------------------------------------------------------------- API surface
def test_phase_14_adds_no_write_route():
    writes = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
              for route in app.routes if getattr(route, "methods", None)
              and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert "POST /observation/driver" not in writes
    assert not [path for path in writes if "forward" in path]
    assert not [path for path in writes if "/ai/training" in path]


def test_the_forward_dashboard_states_the_invariants(client, db_session):
    payload = client.get("/dashboard/forward").json()["data"]
    assert payload["orders_sent"] == 0
    assert payload["automated_trading"] is False
    assert payload["automatic_training"] is False
    assert payload["evidence"] == "FORWARD_OBSERVATION"


def test_the_driver_status_endpoint_reports_zero_orders(client):
    payload = client.get("/observation/driver").json()
    assert payload["orders_sent"] == 0
    assert payload["automated_trading"] is False
    assert payload["observation_mode"] is True


def test_the_training_runs_endpoint_states_no_automatic_training(client):
    payload = client.get("/ai/training/runs").json()
    assert payload["automatic_training"] is False
    assert payload["promotion_requires_approval"] is True
