"""Retraining triggers produce requests, never training runs (sections 26, 27)."""
from datetime import datetime, timedelta, timezone

import pytest

from ai.training.retraining import (
    RequestState, RetrainingPolicy, RetrainingRequest, RetrainingTrigger,
)

NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)


def policy(**kwargs):
    return RetrainingPolicy(**kwargs)


def test_no_trigger_means_no_request_is_warranted():
    request = policy().evaluate(new_observations=0, now=NOW)
    assert not request.triggered and request.state is RequestState.PENDING


def test_enough_new_observations_triggers():
    request = policy(minimum_new_observations=500).evaluate(new_observations=600, now=NOW)
    assert RetrainingTrigger.NEW_OBSERVATIONS in request.triggers


def test_too_few_new_observations_does_not_trigger():
    request = policy(minimum_new_observations=500).evaluate(new_observations=100, now=NOW)
    assert RetrainingTrigger.NEW_OBSERVATIONS not in request.triggers


def test_the_schedule_triggers_after_the_interval():
    request = policy(scheduled_interval_days=7).evaluate(
        last_training=NOW - timedelta(days=10), now=NOW)
    assert RetrainingTrigger.SCHEDULED in request.triggers


def test_a_recent_training_does_not_trigger_the_schedule():
    request = policy(scheduled_interval_days=7).evaluate(
        last_training=NOW - timedelta(days=2), now=NOW)
    assert RetrainingTrigger.SCHEDULED not in request.triggers


def test_performance_degradation_triggers():
    request = policy(performance_degradation=0.10).evaluate(
        baseline_score=0.62, current_score=0.45, now=NOW)
    assert RetrainingTrigger.PERFORMANCE_DEGRADATION in request.triggers


def test_drift_triggers():
    assert RetrainingTrigger.FEATURE_DRIFT in policy().evaluate(drift_flagged=True,
                                                                now=NOW).triggers


def test_a_manual_request_triggers():
    assert RetrainingTrigger.MANUAL in policy().evaluate(manual=True, now=NOW).triggers


def test_several_triggers_are_all_recorded():
    request = policy(minimum_new_observations=100).evaluate(
        new_observations=500, drift_flagged=True, manual=True, now=NOW)
    assert len(request.triggers) == 3


def test_a_request_never_trains_or_promotes_by_itself():
    payload = policy().evaluate(manual=True, now=NOW).as_dict()
    assert payload["auto_trains"] is False
    assert payload["auto_promotes"] is False


def test_the_policy_has_no_training_method():
    for name in ("train", "fit", "retrain", "promote", "deploy"):
        assert not hasattr(RetrainingPolicy, name), name


def test_approving_a_request_requires_a_human_and_a_reason():
    request = policy().evaluate(manual=True, now=NOW)
    with pytest.raises(ValueError, match="named human"):
        policy().approve(request, approved_by="", reason="ok")
    with pytest.raises(ValueError, match="reason"):
        policy().approve(request, approved_by="nvphu", reason=" ")


def test_an_approved_request_records_the_approver():
    request = policy().evaluate(manual=True, now=NOW)
    approved = policy().approve(request, approved_by="nvphu", reason="new data available")
    assert approved.state is RequestState.APPROVED and approved.approved_by == "nvphu"


def test_a_rejected_request_records_the_reason():
    request = policy().evaluate(manual=True, now=NOW)
    rejected = policy().reject(request, reason="not enough new data")
    assert rejected.state is RequestState.REJECTED
    assert any("REJECTED" in reason for reason in rejected.reasons)


def test_retraining_always_mints_a_new_version():
    assert RetrainingPolicy.next_version("multitask_mlp.v1") == "multitask_mlp.v2"
    assert RetrainingPolicy.next_version("multitask_mlp.v9") == "multitask_mlp.v10"
    assert RetrainingPolicy.next_version(None) == "multitask_mlp.v1"


def test_a_new_version_never_equals_the_current_one():
    for version in ("multitask_mlp.v1", "custom", "a.b.v3"):
        assert RetrainingPolicy.next_version(version) != version


def test_requests_persist(db_session):
    from database.models import RetrainingRequestRecord
    from database.repositories import LearningRepository

    request = policy().evaluate(manual=True, now=NOW)
    LearningRepository(db_session).save_retraining_request(request, model_id="m1")
    row = db_session.query(RetrainingRequestRecord).one()
    assert row.state == "PENDING" and row.model_id == "m1"
    assert row.request_json["auto_trains"] is False
