"""The model must beat meaningful baselines or be marked NO_EDGE (section 18)."""
import numpy as np
import pytest

from ai.evaluation.significance import EdgeVerdict, SignificanceEvaluator
from ai.models.multitask import MultiTaskConfig
from ai.models.rule_baselines import (
    ADXBaseline, CombinedRuleBaseline, IchimokuBaseline, MajorityBaseline,
    MomentumBaseline, RSIBaseline, RandomBaseline, RegimeBaseline, all_baselines,
)
from ai.training.forward_trainer import ForwardTrainer
from tests.phase13_helpers import build_dataset

FEATURES = ("trend_m15", "rsi_m15", "adx_m15", "htf_score", "ichimoku_cross_m15")


def test_every_documented_baseline_exists():
    names = set(all_baselines(FEATURES))
    assert names == {"random", "majority", "momentum", "regime", "rsi", "ichimoku",
                     "adx", "combined_rules"}


def test_every_baseline_emits_valid_probabilities():
    matrix = np.zeros((5, len(FEATURES)))
    labels = np.zeros(5, dtype=int)
    for name, baseline in all_baselines(FEATURES).items():
        baseline.fit(matrix, labels)
        probabilities = baseline.predict_proba(matrix)
        assert probabilities.shape == (5, 3), name
        assert np.allclose(probabilities.sum(axis=1), 1.0), name


def test_the_majority_baseline_learns_the_training_distribution():
    baseline = MajorityBaseline(FEATURES)
    baseline.fit(np.zeros((10, len(FEATURES))), np.array([0] * 8 + [1, 2]))
    assert baseline.predict_proba(np.zeros((1, len(FEATURES))))[0].argmax() == 0


def test_the_momentum_baseline_follows_the_trend_column():
    matrix = np.zeros((2, len(FEATURES)))
    matrix[0, 0] = 1.0
    matrix[1, 0] = -1.0
    predictions = MomentumBaseline(FEATURES).predict_proba(matrix).argmax(axis=1)
    assert predictions[0] == 0 and predictions[1] == 1


def test_the_rsi_baseline_is_mean_reverting():
    matrix = np.zeros((2, len(FEATURES)))
    matrix[0, 1] = 20.0
    matrix[1, 1] = 80.0
    predictions = RSIBaseline(FEATURES).predict_proba(matrix).argmax(axis=1)
    assert predictions[0] == 0 and predictions[1] == 1


def test_the_adx_baseline_stays_neutral_without_a_trend():
    matrix = np.zeros((1, len(FEATURES)))
    matrix[0, 0] = 1.0
    matrix[0, 2] = 5.0
    assert ADXBaseline(FEATURES).predict_proba(matrix).argmax(axis=1)[0] == 2


def test_the_ichimoku_baseline_follows_the_cross():
    matrix = np.zeros((2, len(FEATURES)))
    matrix[0, 4] = 0.001
    matrix[1, 4] = -0.001
    predictions = IchimokuBaseline(FEATURES).predict_proba(matrix).argmax(axis=1)
    assert predictions[0] == 0 and predictions[1] == 1


def test_a_baseline_falls_back_when_its_feature_is_absent():
    baseline = MomentumBaseline(("unrelated",))
    probabilities = baseline.predict_proba(np.zeros((3, 1)))
    assert probabilities.shape == (3, 3)


def test_the_combined_baseline_votes_across_its_members():
    matrix = np.zeros((1, len(FEATURES)))
    matrix[0, 0] = 1.0
    matrix[0, 3] = 0.5
    probabilities = CombinedRuleBaseline(FEATURES).predict_proba(matrix)
    assert probabilities[0].argmax() == 0


def test_training_reports_a_score_for_every_baseline():
    report = ForwardTrainer(config=MultiTaskConfig(epochs=40, hidden_units=12)).train(
        build_dataset(count=300))
    assert set(report.baselines) == set(all_baselines(("trend_m15",)))
    assert all(0.0 <= score <= 1.0 for score in report.baselines.values())


def test_failing_to_beat_the_baselines_forces_no_edge():
    """Statistical significance alone is not enough to claim an edge."""
    evaluator = SignificanceEvaluator(minimum_samples=10, bootstrap_samples=200)
    trainer = ForwardTrainer(config=MultiTaskConfig(epochs=5, hidden_units=8),
                             significance=evaluator)
    dataset = build_dataset(count=300)
    from ai.dataset.builder import Partition

    verdict = trainer._edge(dataset.test, beats_all=False)
    assert verdict["verdict"] == str(EdgeVerdict.NO_EDGE)
    assert "DOES_NOT_BEAT_BASELINES" in verdict["reasons"]


def test_the_record_states_whether_baselines_were_beaten():
    report = ForwardTrainer(config=MultiTaskConfig(epochs=40, hidden_units=12)).train(
        build_dataset(count=300))
    comparison = report.record.baseline_comparison
    assert "beats_all_baselines" in comparison and "scores" in comparison
    assert isinstance(comparison["beats_all_baselines"], bool)
