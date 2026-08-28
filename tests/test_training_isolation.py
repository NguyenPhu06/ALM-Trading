"""Training is isolated from the market loop (sections 10 and 12).

    Do NOT train the model after every observation.
    Do NOT train inside the market cycle.
    Do NOT perform uncontrolled online learning.

These are checked structurally — by parsing the import graph and the source of
the loop — rather than by hoping no future caller wires the two together.
"""
import ast
import inspect
import pathlib

import pytest

from ai.training.pipeline import PipelineStep, TrainingPipeline
from ai.training.train import OnlineLearningRefused, TrainingJob
from config.settings import get_settings
from observation.cycle import ObservationCycle
from observation.driver import ObservationDriver
from observation.ingestion import DatasetIngestor
from observation.outcome import ForwardOutcomeEngine

TRAINING_SYMBOLS = ("ForwardTrainer", "TrainingJob", "TrainingPipeline", "MultiTaskMLP",
                    "fit", "train")
LOOP_MODULES = ("observation/cycle.py", "observation/driver.py",
                "observation/outcome.py", "observation/ingestion.py",
                "observation/lifecycle.py")


def imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
    return names


# --------------------------------------------- 10. no training in the loop
@pytest.mark.parametrize("module", LOOP_MODULES)
def test_no_loop_module_imports_a_trainer(module):
    forbidden = {"ai.training.train", "ai.training.pipeline", "ai.training.forward_trainer",
                 "ai.models.multitask"}
    assert not (imported_modules(pathlib.Path(module)) & forbidden), module


def test_the_observation_cycle_has_no_fit_call():
    source = inspect.getsource(ObservationCycle)
    for token in (".fit(", "ForwardTrainer", "MultiTaskMLP", "TrainingJob"):
        assert token not in source, token


def test_the_driver_has_no_fit_call():
    source = inspect.getsource(ObservationDriver)
    for token in (".fit(", "ForwardTrainer", "TrainingJob", "TrainingPipeline",
                  "MultiTaskMLP"):
        assert token not in source, token


def test_the_driver_exposes_no_training_method():
    for name in ("train", "fit", "retrain", "learn", "update_model"):
        assert not hasattr(ObservationDriver, name), name


def test_resolving_an_outcome_cannot_train():
    source = inspect.getsource(ForwardOutcomeEngine)
    for token in TRAINING_SYMBOLS:
        assert f"{token}(" not in source or token == "train", token


def test_ingestion_writes_data_but_does_not_train():
    source = inspect.getsource(DatasetIngestor)
    assert ".fit(" not in source
    assert "Trainer" not in source


# -------------------------------------------- an explicit job, or nothing
def test_the_job_refuses_to_exist_when_online_learning_is_on(monkeypatch):
    from types import SimpleNamespace

    fake = SimpleNamespace(ai_online_learning_enabled=True, ai_training_enabled=True)
    with pytest.raises(OnlineLearningRefused):
        TrainingJob(fake)


def test_online_learning_is_off_in_the_shipped_settings():
    assert get_settings().ai_online_learning_enabled is False


def test_the_job_reports_zero_orders_and_no_promotion(memory_repository):
    from datetime import datetime, timezone

    from ai.training.train import JobResult

    result = JobResult(datetime.now(timezone.utc), datetime.now(timezone.utc), None,
                       "skipped")
    assert result.orders_sent == 0
    assert result.promoted is False


def test_a_disabled_training_flag_skips_the_run(monkeypatch):
    from types import SimpleNamespace

    fake = SimpleNamespace(ai_online_learning_enabled=False, ai_training_enabled=False)
    job = TrainingJob(fake, trainer=object())
    # The dataset is never touched: the flag is checked before anything reads it.
    result = job.run(object())
    assert not result.ok
    assert result.context["skipped"] is True


# ------------------------------------------------------ 12. the ten steps
def test_the_pipeline_has_exactly_the_documented_steps():
    assert [str(step) for step in PipelineStep] == [
        "LOAD", "VALIDATE", "LEAKAGE", "SPLIT", "PREPROCESS", "TRAIN", "EVALUATE",
        "COMPARE", "REPORT", "REGISTER"]


def test_the_pipeline_stops_at_register_and_never_promotes():
    source = inspect.getsource(TrainingPipeline)
    assert "promote(" not in source
    assert "ApprovalToken" not in source


def test_an_empty_observation_list_fails_at_load():
    report = TrainingPipeline().run([], [])
    assert not report.ok
    assert report.failed_step is PipelineStep.LOAD


def test_the_pipeline_report_states_the_invariants():
    payload = TrainingPipeline().run([], []).as_dict()
    assert payload["promoted"] is False
    assert payload["orders_sent"] == 0
    assert payload["requires_human_approval"] is True
    assert payload["evidence"] == "FORWARD_OBSERVATION"


def test_no_pipeline_module_reaches_execution():
    forbidden = ("MT5ExecutionClient", "send_market_order", "order_send", "ExecutionGuard",
                 "ExecutionKillSwitch", "execution.mt5")
    for module in ("ai/training/train.py", "ai/training/pipeline.py",
                   "ai/training/evaluation.py", "ai/training/triggers.py"):
        source = pathlib.Path(module).read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{module}:{token}"
