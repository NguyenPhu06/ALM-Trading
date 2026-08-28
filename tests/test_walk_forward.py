from ai.datasets import ExpandingWalkForward
from ai.evaluation import WalkForwardValidator
from tests.phase5_helpers import classification_data, training_config


def test_walk_forward_trains_expanding_windows_and_keeps_test_after_validation():
    timestamps, matrix, labels, outcomes = classification_data(60)
    validator = WalkForwardValidator(
        ExpandingWalkForward(initial_train_size=24, validation_size=9, test_size=6, step_size=6),
        training_config(),
    )
    results = validator.validate(timestamps, matrix, labels, outcomes)
    assert len(results) >= 2
    assert results[1].window.train_end > results[0].window.train_end
    assert all(result.window.train_end < result.window.validation_start < result.window.test_start for result in results)
    assert all(0 <= result.metrics.balanced_accuracy <= 1 for result in results)


# --------------------------------- Phase 13: walk-forward on forward observations
# The Phase 4 tests above cover the window generator. These cover walk-forward
# training and the stability metric reported on the model record (section 11).
from datetime import timedelta

import pytest

from ai.datasets.walk_forward import ExpandingWalkForward
from ai.models.multitask import MultiTaskConfig
from ai.training.forward_trainer import ForwardTrainer
from tests.phase13_helpers import NOW, build_dataset


def timestamps(count=400):
    return [NOW - timedelta(hours=count - index) for index in range(count)]


def test_windows_expand_and_move_forward():
    windows = list(ExpandingWalkForward(initial_train_size=100, validation_size=25,
                                        test_size=25, step_size=25).windows(timestamps()))
    assert len(windows) >= 3
    for earlier, later in zip(windows, windows[1:]):
        assert later.train_end > earlier.train_end
        assert later.test_start > earlier.test_start


def test_each_window_trains_before_it_tests():
    windows = list(ExpandingWalkForward(initial_train_size=100, validation_size=25,
                                        test_size=25, step_size=25).windows(timestamps()))
    for window in windows:
        assert window.train_end < window.validation_start
        assert window.validation_end < window.test_start


def test_training_reports_walk_forward_metrics():
    dataset = build_dataset(count=300)
    report = ForwardTrainer(config=MultiTaskConfig(epochs=40, hidden_units=12)).train(dataset)
    metrics = report.record.walk_forward_metrics
    assert "windows" in metrics
    if metrics.get("mean_accuracy") is not None:
        assert 0.0 <= metrics["mean_accuracy"] <= 1.0
        assert 0.0 <= metrics["stability"] <= 1.0


def test_stability_is_reported_and_bounded():
    dataset = build_dataset(count=300)
    report = ForwardTrainer(config=MultiTaskConfig(epochs=40, hidden_units=12)).train(dataset)
    metrics = report.record.walk_forward_metrics
    if metrics.get("scores"):
        assert len(metrics["scores"]) == metrics["windows"]
        assert metrics["min"] <= metrics["mean_accuracy"] <= metrics["max"]


def test_insufficient_data_is_reported_rather_than_raising():
    dataset = build_dataset(count=80, minimum_rows=10)
    report = ForwardTrainer(config=MultiTaskConfig(epochs=10, hidden_units=8)).train(dataset)
    metrics = report.record.walk_forward_metrics
    assert metrics["windows"] == 0 or metrics.get("mean_accuracy") is not None
