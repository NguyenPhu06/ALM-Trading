"""Drift detection in the forward loop (section 21).

Six kinds of drift are monitored. All of them do exactly one thing: raise an
alert. None of them retrains, demotes a champion, changes a threshold or touches
an execution flag.
"""
import inspect

import pytest

from ai.model_registry.drift import (
    DriftKind,
    DriftMonitor,
    DriftSeverity,
    population_stability_index,
)
from config.settings import get_settings
from monitoring.alerts import AlertEngine, AlertRouter, AlertType


def monitor(**kwargs):
    return DriftMonitor(**kwargs)


def shifted(values, offset):
    return [value + offset for value in values]


REFERENCE = [round(0.01 * index, 4) for index in range(200)]


# ------------------------------------------------------------- the measure
def test_identical_distributions_have_no_drift():
    assert population_stability_index(REFERENCE, REFERENCE) == pytest.approx(0.0, abs=1e-9)


def test_a_shifted_distribution_registers_drift():
    assert population_stability_index(REFERENCE, shifted(REFERENCE, 5.0)) > 0.2


def test_a_slightly_shifted_distribution_registers_less_drift():
    small = population_stability_index(REFERENCE, shifted(REFERENCE, 0.05))
    large = population_stability_index(REFERENCE, shifted(REFERENCE, 5.0))
    assert small < large


# -------------------------------------------------------- the six signals
def test_feature_drift_is_detected():
    signal = monitor().feature_drift({"rsi_m15": REFERENCE},
                                     {"rsi_m15": shifted(REFERENCE, 5.0)})
    assert signal.kind is DriftKind.FEATURE
    assert signal.flagged
    assert signal.context["worst_feature"] == "rsi_m15"


def test_prediction_drift_is_detected():
    signal = monitor().prediction_drift(REFERENCE, shifted(REFERENCE, 5.0))
    assert signal.kind is DriftKind.PREDICTION
    assert signal.flagged


def test_performance_drift_is_detected():
    signal = monitor().performance_drift(0.70, 0.40)
    assert signal.kind is DriftKind.PERFORMANCE
    assert signal.flagged


def test_a_stable_score_is_not_performance_drift():
    assert not monitor().performance_drift(0.70, 0.695).flagged


def test_regime_drift_is_detected():
    signal = monitor().regime_drift({"BULL": 100, "BEAR": 10},
                                    {"BULL": 10, "BEAR": 100})
    assert signal.kind is DriftKind.REGIME
    assert signal.flagged


def test_a_stable_regime_mix_is_not_drift():
    counts = {"BULL": 100, "BEAR": 100}
    assert not monitor().regime_drift(counts, counts).flagged


def test_the_full_evaluation_reports_every_signal_it_was_given():
    report = monitor().evaluate(
        reference_features={"rsi_m15": REFERENCE},
        current_features={"rsi_m15": shifted(REFERENCE, 5.0)},
        reference_predictions=REFERENCE,
        current_predictions=shifted(REFERENCE, 5.0),
        baseline_score=0.70, current_score=0.40,
        reference_regimes={"BULL": 100, "BEAR": 10},
        current_regimes={"BULL": 10, "BEAR": 100})
    assert report.flagged
    assert len(report.signals) >= 4


def test_an_empty_evaluation_flags_nothing():
    assert not monitor().evaluate().flagged


# ------------------------------------------------------------ FLAG_ONLY
def test_every_signal_is_flag_only():
    report = monitor().evaluate(baseline_score=0.70, current_score=0.30)
    for signal in report.signals:
        assert signal.as_dict()["action"] == "FLAG_ONLY"


def test_the_monitor_cannot_retrain():
    source = inspect.getsource(DriftMonitor)
    for token in ("ForwardTrainer", "TrainingJob", "TrainingPipeline", ".fit(", "train("):
        assert token not in source, token


def test_the_monitor_cannot_promote_or_demote():
    source = inspect.getsource(DriftMonitor)
    for token in ("promote", "demote", "transition", "ApprovalToken"):
        assert token not in source, token


def test_the_monitor_cannot_touch_an_execution_flag():
    source = inspect.getsource(DriftMonitor)
    for token in ("kill_switch", "mt5_execution_enabled", "demo_trading_enabled",
                  "live_trading_enabled", "order_send"):
        assert token not in source, token


def test_detecting_drift_changes_no_setting():
    before = {name: getattr(get_settings(), name) for name in
              ("live_trading_enabled", "demo_trading_enabled", "mt5_execution_enabled",
               "execution_kill_switch", "observation_mode", "ai_auto_promote",
               "ai_automatic_training")}
    monitor().evaluate(baseline_score=0.9, current_score=0.1)
    after = {name: getattr(get_settings(), name) for name in before}
    assert after == before


# ------------------------------------------------------------------ alert
def test_drift_raises_its_own_alert_type():
    report = monitor().evaluate(baseline_score=0.70, current_score=0.30)
    alerts = AlertRouter(AlertEngine()).model_drift(report=report, model_id="m1")
    assert alerts[0].alert_type is AlertType.MODEL_DRIFT
    assert alerts[0].context["action"] == "FLAG_ONLY"
    assert alerts[0].context["model_id"] == "m1"


def test_the_drift_alert_names_the_kinds_that_fired():
    report = monitor().evaluate(baseline_score=0.70, current_score=0.30)
    alert = AlertRouter(AlertEngine()).model_drift(report=report)[0]
    assert "PERFORMANCE" in alert.message


def test_severity_is_reported_not_acted_on():
    signal = monitor().performance_drift(0.90, 0.10)
    assert signal.severity in set(DriftSeverity)
    assert signal.as_dict()["action"] == "FLAG_ONLY"


# ---------------------------------------------------- persistence is a record
def test_a_drift_event_is_stored_as_flag_only(db_session):
    from database.models import ModelDriftEventRecord
    from database.repositories.learning import LearningRepository

    report = monitor().evaluate(baseline_score=0.70, current_score=0.30)
    LearningRepository(db_session).save_drift(report, model_id="m1")
    rows = db_session.query(ModelDriftEventRecord).all()
    assert rows
    assert all(row.action == "FLAG_ONLY" for row in rows)
