"""Training triggers (section 11).

Defaults: manual_training=true, automatic_training=false. A trigger proposes;
only a human starts a run.
"""
from datetime import timedelta

import pytest

from ai.training.retraining import RetrainingTrigger
from ai.training.triggers import TrainingTriggerPolicy, TriggerSettings
from config.settings import get_settings
from tests.phase14_helpers import NOW


def settings_for(**overrides):
    base = TriggerSettings.from_config()
    values = {name: getattr(base, name) for name in
              ("minimum_new_observations", "scheduled_training", "manual_training",
               "automatic_training", "performance_degradation", "drift_detected")}
    values.update(overrides)
    return TriggerSettings(**values)


# ----------------------------------------------------------------- defaults
def test_manual_training_is_on_by_default():
    assert TriggerSettings().manual_training is True


def test_automatic_training_is_off_by_default():
    assert TriggerSettings().automatic_training is False


def test_the_configured_defaults_match_the_documented_ones():
    config = TriggerSettings.from_config()
    assert config.manual_training is True
    assert config.automatic_training is False


def test_automatic_training_is_refused_at_startup():
    assert get_settings().ai_automatic_training is False


def test_yaml_alone_cannot_enable_automatic_training(monkeypatch):
    """The flag is read from Settings, never from the YAML block."""
    import ai.training.triggers as module

    monkeypatch.setattr(module, "load_yaml",
                        lambda: {"phase_14": {"triggers": {"automatic_training": True}}})
    assert TriggerSettings.from_config().automatic_training is False


# ----------------------------------------------------------- every trigger
def test_a_manual_request_fires():
    decision = TrainingTriggerPolicy().evaluate(manual=True, now=NOW)
    assert RetrainingTrigger.MANUAL in decision.fired


def test_enough_new_observations_fires():
    decision = TrainingTriggerPolicy().evaluate(new_observations=10_000, now=NOW)
    assert RetrainingTrigger.NEW_OBSERVATIONS in decision.fired


def test_too_few_new_observations_does_not_fire():
    decision = TrainingTriggerPolicy().evaluate(new_observations=1, now=NOW)
    assert RetrainingTrigger.NEW_OBSERVATIONS not in decision.fired


def test_performance_degradation_fires():
    decision = TrainingTriggerPolicy().evaluate(baseline_score=0.70, current_score=0.50,
                                                now=NOW)
    assert RetrainingTrigger.PERFORMANCE_DEGRADATION in decision.fired


def test_a_small_performance_drop_does_not_fire():
    decision = TrainingTriggerPolicy().evaluate(baseline_score=0.70, current_score=0.695,
                                                now=NOW)
    assert RetrainingTrigger.PERFORMANCE_DEGRADATION not in decision.fired


def test_drift_fires_when_the_drift_trigger_is_enabled():
    decision = TrainingTriggerPolicy().evaluate(drift_flagged=True, now=NOW)
    assert RetrainingTrigger.FEATURE_DRIFT in decision.fired


def test_scheduled_training_is_suppressed_by_default():
    decision = TrainingTriggerPolicy().evaluate(
        last_training=NOW - timedelta(days=90), now=NOW)
    assert RetrainingTrigger.SCHEDULED not in decision.fired
    assert any("SCHEDULED_TRAINING_DISABLED" in reason
               for reason in decision.suppressed)


def test_scheduled_training_fires_when_enabled():
    instance = TrainingTriggerPolicy(config=settings_for(scheduled_training=True))
    decision = instance.evaluate(last_training=NOW - timedelta(days=90), now=NOW)
    assert RetrainingTrigger.SCHEDULED in decision.fired


def test_disabling_manual_training_suppresses_it():
    instance = TrainingTriggerPolicy(config=settings_for(manual_training=False))
    decision = instance.evaluate(manual=True, now=NOW)
    assert RetrainingTrigger.MANUAL not in decision.fired
    assert any("MANUAL_TRAINING_DISABLED" in reason for reason in decision.suppressed)


def test_disabling_the_drift_trigger_suppresses_it():
    instance = TrainingTriggerPolicy(config=settings_for(drift_detected=False))
    decision = instance.evaluate(drift_flagged=True, now=NOW)
    assert RetrainingTrigger.FEATURE_DRIFT not in decision.fired


# ---------------------------------------------------- a trigger is not a run
def test_a_fired_trigger_never_starts_training_automatically():
    decision = TrainingTriggerPolicy().evaluate(manual=True, new_observations=10_000,
                                                drift_flagged=True, now=NOW)
    assert decision.triggered
    assert decision.may_start_automatically is False
    assert decision.requires_human is True


def test_the_decision_says_human_approval_is_required():
    decision = TrainingTriggerPolicy().evaluate(manual=True, now=NOW)
    assert "HUMAN_APPROVAL_REQUIRED" in decision.reasons


def test_the_request_states_that_it_neither_trains_nor_promotes():
    payload = TrainingTriggerPolicy().evaluate(manual=True, now=NOW).request.as_dict()
    assert payload["auto_trains"] is False
    assert payload["auto_promotes"] is False


def test_the_serialised_decision_repeats_the_guarantee():
    payload = TrainingTriggerPolicy().evaluate(manual=True, now=NOW).as_dict()
    assert payload["may_start_automatically"] is False
    assert payload["requires_human"] is True


def test_nothing_fires_when_nothing_happened():
    decision = TrainingTriggerPolicy().evaluate(now=NOW)
    assert not decision.triggered
    assert decision.may_start_automatically is False
