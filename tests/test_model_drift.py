"""Drift is FLAGGED, never acted on (section 25)."""
import numpy as np
import pytest

from ai.model_registry.drift import (
    DriftKind, DriftMonitor, DriftSeverity, population_stability_index,
)


def test_identical_distributions_have_near_zero_psi():
    rng = np.random.default_rng(1)
    values = rng.normal(0, 1, 500)
    assert population_stability_index(values, values) < 0.01


def test_a_shifted_distribution_has_a_large_psi():
    rng = np.random.default_rng(1)
    reference = rng.normal(0, 1, 500)
    shifted = rng.normal(5, 1, 500)
    assert population_stability_index(reference, shifted) > 0.5


def test_psi_is_zero_for_degenerate_input():
    assert population_stability_index([1.0], [1.0]) == 0.0


def test_feature_drift_flags_the_worst_feature():
    rng = np.random.default_rng(2)
    reference = {"a": rng.normal(0, 1, 400), "b": rng.normal(0, 1, 400)}
    current = {"a": rng.normal(0, 1, 400), "b": rng.normal(6, 1, 400)}
    signal = DriftMonitor().feature_drift(reference, current)
    assert signal.kind is DriftKind.FEATURE
    assert signal.flagged and signal.context["worst_feature"] == "b"


def test_stable_features_are_not_flagged():
    rng = np.random.default_rng(3)
    reference = {"a": rng.normal(0, 1, 400)}
    current = {"a": rng.normal(0, 1, 400)}
    assert not DriftMonitor().feature_drift(reference, current).flagged


def test_prediction_drift_is_detected():
    rng = np.random.default_rng(4)
    signal = DriftMonitor().prediction_drift(rng.uniform(0, 1, 500),
                                             rng.uniform(0.8, 1.0, 500))
    assert signal.kind is DriftKind.PREDICTION and signal.flagged


def test_performance_drift_measures_the_score_drop():
    signal = DriftMonitor(performance_threshold=0.10).performance_drift(0.62, 0.45)
    assert signal.kind is DriftKind.PERFORMANCE
    assert signal.metric == pytest.approx(0.17)
    assert signal.flagged and signal.severity is DriftSeverity.MAJOR


def test_a_small_score_drop_is_minor_not_major():
    signal = DriftMonitor(performance_threshold=0.10).performance_drift(0.62, 0.56)
    assert signal.severity is DriftSeverity.MINOR and not signal.flagged


def test_regime_drift_compares_the_regime_mix():
    signal = DriftMonitor().regime_drift({"BULL": 90, "RANGE": 10},
                                         {"BULL": 5, "RANGE": 95})
    assert signal.kind is DriftKind.REGIME and signal.flagged


def test_every_signal_is_flag_only():
    """Detection must never trigger retraining or promotion."""
    rng = np.random.default_rng(5)
    report = DriftMonitor().evaluate(
        reference_features={"a": rng.normal(0, 1, 300)},
        current_features={"a": rng.normal(9, 1, 300)},
        reference_predictions=rng.uniform(0, 1, 300),
        current_predictions=rng.uniform(0.9, 1, 300),
        baseline_score=0.6, current_score=0.3,
        reference_regimes={"BULL": 80, "BEAR": 20},
        current_regimes={"BULL": 10, "BEAR": 90})
    assert report.flagged and report.severity is DriftSeverity.MAJOR
    assert all(signal.action == "FLAG_ONLY" for signal in report.signals)
    assert report.as_dict()["action"] == "FLAG_ONLY"


def test_the_monitor_has_no_retrain_or_promote_method():
    for name in ("retrain", "promote", "deploy", "fit", "train"):
        assert not hasattr(DriftMonitor, name), name


def test_an_empty_evaluation_reports_no_drift():
    report = DriftMonitor().evaluate()
    assert not report.flagged and report.severity is DriftSeverity.NONE


def test_drift_events_persist_with_flag_only(db_session):
    from database.models import ModelDriftEventRecord
    from database.repositories import LearningRepository

    rng = np.random.default_rng(6)
    report = DriftMonitor().evaluate(baseline_score=0.6, current_score=0.2)
    LearningRepository(db_session).save_drift(report, model_id="m1")
    rows = db_session.query(ModelDriftEventRecord).all()
    assert rows and all(row.action == "FLAG_ONLY" for row in rows)
    assert rows[0].model_id == "m1"
