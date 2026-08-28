"""Probability calibration (section 15)."""
import numpy as np
import pytest

from ai.evaluation.calibration import calibration_report
from ai.models.multitask import MultiTaskConfig
from ai.training.forward_trainer import ForwardTrainer, probabilistic_scores
from tests.phase13_helpers import build_dataset


def test_brier_score_is_zero_for_perfect_predictions():
    labels = np.array([0, 1, 2])
    perfect = np.eye(3)
    assert probabilistic_scores(labels, perfect)["brier_score"] == pytest.approx(0.0)


def test_brier_score_is_worst_for_confidently_wrong_predictions():
    labels = np.array([0, 0])
    wrong = np.array([[0.0, 1.0, 0.0], [0.0, 1.0, 0.0]])
    assert probabilistic_scores(labels, wrong)["brier_score"] == pytest.approx(2.0)


def test_log_loss_is_near_zero_for_confident_correct_predictions():
    labels = np.array([0, 1])
    confident = np.array([[0.99, 0.005, 0.005], [0.005, 0.99, 0.005]])
    assert probabilistic_scores(labels, confident)["log_loss"] < 0.05


def test_log_loss_grows_when_confidence_is_misplaced():
    labels = np.array([0, 0])
    good = np.array([[0.8, 0.1, 0.1], [0.8, 0.1, 0.1]])
    bad = np.array([[0.2, 0.4, 0.4], [0.2, 0.4, 0.4]])
    assert probabilistic_scores(labels, bad)["log_loss"] > probabilistic_scores(labels, good)["log_loss"]


def test_uniform_predictions_have_a_known_log_loss():
    labels = np.array([0, 1, 2])
    uniform = np.full((3, 3), 1 / 3)
    assert probabilistic_scores(labels, uniform)["log_loss"] == pytest.approx(np.log(3))


def test_empty_input_returns_none_rather_than_raising():
    scores = probabilistic_scores(np.array([], dtype=int), np.empty((0, 3)))
    assert scores["brier_score"] is None and scores["log_loss"] is None


def test_a_calibration_curve_is_produced_per_class():
    labels = np.random.default_rng(2).integers(0, 3, 200)
    probabilities = np.random.default_rng(3).dirichlet(np.ones(3), 200)
    report = calibration_report(labels, probabilities, bins=10)
    assert report.bins_by_class and report.expected_calibration_error


def test_calibration_carries_an_uncalibrated_warning():
    """Confidence must not be read as a true probability without evidence."""
    labels = np.random.default_rng(2).integers(0, 3, 100)
    probabilities = np.random.default_rng(3).dirichlet(np.ones(3), 100)
    report = calibration_report(labels, probabilities, bins=5)
    assert report.warning == "MODEL_CONFIDENCE_IS_UNCALIBRATED"


def test_a_trained_model_reports_calibration_metrics():
    report = ForwardTrainer(config=MultiTaskConfig(epochs=40, hidden_units=12)).train(
        build_dataset(count=300))
    calibration = report.record.calibration
    assert calibration.get("brier_score") is not None
    assert calibration.get("log_loss") is not None
    assert "expected_calibration_error" in calibration
