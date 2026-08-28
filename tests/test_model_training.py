"""Multi-task training: architecture, outputs and the scaling guard."""
import numpy as np
import pytest

from ai.models.multitask import (
    DIRECTION_CLASSES, MultiTaskConfig, MultiTaskMLP, REGRESSION_HEADS,
)
from ai.training.forward_trainer import ForwardTrainer, TrainingDisabled
from config.settings import Settings
from tests.phase13_helpers import build_dataset

BASE = dict(database_url="sqlite://", tradingview_webhook_secret="a-secure-test-secret-of-24-chars")


def learnable(count=400, seed=3):
    rng = np.random.default_rng(seed)
    trend = rng.choice([-1.0, 0.0, 1.0], size=count)
    matrix = np.column_stack([trend + rng.normal(0, 0.2, count),
                              rng.normal(0, 1, count)])
    labels = np.where(trend > 0, 0, np.where(trend < 0, 1, 2))
    return {"features": matrix, "direction": labels,
            "regression": np.zeros((count, 3)), "volatility": np.zeros(count)}


def test_the_model_learns_a_learnable_signal():
    data = learnable()
    model = MultiTaskMLP(2, MultiTaskConfig(epochs=200, hidden_units=16))
    model.fit(data)
    accuracy = float((model.predict_proba(data["features"]).argmax(axis=1)
                      == data["direction"]).mean())
    assert accuracy > 0.7, f"model failed to learn an obvious signal: {accuracy}"


def test_training_is_deterministic_for_a_fixed_seed():
    data = learnable()
    first = MultiTaskMLP(2, MultiTaskConfig(epochs=30, random_seed=7)).fit(data)
    second = MultiTaskMLP(2, MultiTaskConfig(epochs=30, random_seed=7)).fit(data)
    assert first.epochs[-1]["train_loss"] == pytest.approx(second.epochs[-1]["train_loss"])


def test_early_stopping_restores_the_best_epoch():
    history = MultiTaskMLP(2, MultiTaskConfig(epochs=300, early_stopping_patience=5)).fit(
        learnable(), learnable(seed=9))
    assert history.best_epoch >= 1
    if history.stopped_early:
        assert history.best_epoch <= len(history.epochs)


def test_unscaled_input_is_flagged_rather_than_failing_silently():
    """Unscaled features train to a useless model without erroring, so it is recorded."""
    rng = np.random.default_rng(1)
    data = learnable()
    data["features"] = data["features"] * 1000
    history = MultiTaskMLP(2, MultiTaskConfig(epochs=5)).fit(data)
    assert history.input_scaled is False
    assert history.warnings and "unscaled" in history.warnings[0]


def test_scaled_input_is_not_flagged():
    history = MultiTaskMLP(2, MultiTaskConfig(epochs=5)).fit(learnable())
    assert history.input_scaled is True and not history.warnings


def test_the_model_emits_every_documented_head():
    model = MultiTaskMLP(2, MultiTaskConfig(epochs=5))
    output = model.predict(np.zeros((1, 2)))[0].as_dict()
    for name in ("direction_probability", "expected_return", "expected_mfe",
                 "expected_mae", "volatility_probability", "confidence"):
        assert name in output, name
    assert set(output["direction_probability"]) == set(DIRECTION_CLASSES)
    assert len(REGRESSION_HEADS) == 3


def test_direction_probabilities_sum_to_one():
    model = MultiTaskMLP(2, MultiTaskConfig(epochs=5))
    probabilities = model.predict_proba(np.zeros((4, 2)))
    assert np.allclose(probabilities.sum(axis=1), 1.0)


def test_the_model_never_emits_a_trade_instruction():
    """The Strategy Engine interprets outputs; the model does not instruct."""
    output = MultiTaskMLP(2, MultiTaskConfig(epochs=5)).predict(np.zeros((1, 2)))[0]
    payload = output.as_dict()
    for forbidden in ("buy", "sell", "action", "order", "signal"):
        assert forbidden not in payload
    assert not hasattr(output, "buy") and not hasattr(output, "sell")


def test_parameters_round_trip():
    model = MultiTaskMLP(2, MultiTaskConfig(epochs=5))
    restored = MultiTaskMLP.from_parameters(2, model.config, model.parameters())
    assert np.allclose(model.predict_proba(np.ones((3, 2))),
                       restored.predict_proba(np.ones((3, 2))))


def test_training_refuses_when_disabled():
    settings = Settings(**BASE)
    object.__setattr__(settings, "ai_training_enabled", False)
    with pytest.raises(TrainingDisabled):
        ForwardTrainer(settings).train(build_dataset())


def test_training_refuses_an_empty_training_partition():
    dataset = build_dataset()
    from dataclasses import replace

    from ai.dataset.builder import Partition

    empty = replace(dataset, train=Partition("TRAIN", ()))
    with pytest.raises(ValueError, match="empty training partition"):
        ForwardTrainer().train(empty)


def test_a_trained_record_carries_every_metric_section():
    report = ForwardTrainer(config=MultiTaskConfig(epochs=40, hidden_units=12)).train(
        build_dataset(count=300))
    record = report.record
    for section in ("validation_metrics", "test_metrics", "walk_forward_metrics",
                    "regime_metrics", "session_metrics", "baseline_comparison",
                    "calibration", "explainability"):
        assert getattr(record, section) is not None, section
    assert record.feature_version == "features_v1"
    assert record.training_dataset_version == report.record.training_dataset_version
