"""The observation state machine (sections 4 and 5)."""
from datetime import timedelta

import pytest

from observation.lifecycle import (
    ALLOWED_TRANSITIONS,
    FAILURE_STATES,
    HAPPY_PATH,
    LifecycleError,
    ObservationStatus,
    observation_from_cycle,
)
from tests.phase14_helpers import NOW, FakeRegime, FakeResult, observation, snapshot


# ------------------------------------------------------- 4. the state machine
def test_the_happy_path_is_exactly_the_documented_sequence():
    assert [str(state) for state in HAPPY_PATH] == [
        "CREATED", "FEATURES_CAPTURED", "NN_PREDICTED", "STRATEGY_EVALUATED",
        "RISK_EVALUATED", "OBSERVING", "HORIZON_REACHED", "OUTCOME_CALCULATED",
        "LABELED", "DATASET_READY"]


def test_the_four_failure_states_are_exactly_the_documented_ones():
    assert {str(state) for state in FAILURE_STATES} == {
        "DATA_INVALID", "MODEL_ERROR", "CALCULATION_ERROR", "TIMEOUT"}


def test_each_step_advances_by_exactly_one():
    record = observation(status=ObservationStatus.CREATED)
    for target in HAPPY_PATH[1:]:
        record = record.advance(target, now=NOW)
    assert record.status is ObservationStatus.DATASET_READY


def test_skipping_a_step_is_refused():
    record = observation(status=ObservationStatus.CREATED)
    with pytest.raises(LifecycleError, match="not an allowed transition"):
        record.advance(ObservationStatus.OBSERVING)


def test_going_backwards_is_refused():
    record = observation(status=ObservationStatus.OBSERVING)
    with pytest.raises(LifecycleError):
        record.advance(ObservationStatus.NN_PREDICTED)


def test_repeating_a_step_is_refused():
    record = observation(status=ObservationStatus.OBSERVING)
    with pytest.raises(LifecycleError):
        record.advance(ObservationStatus.OBSERVING)


def test_every_live_state_can_fail():
    for state in HAPPY_PATH[:-1]:
        allowed = ALLOWED_TRANSITIONS[state]
        assert FAILURE_STATES <= allowed, state


@pytest.mark.parametrize("failure", sorted(FAILURE_STATES, key=str))
def test_a_failure_state_is_terminal(failure):
    record = observation(status=ObservationStatus.OBSERVING).fail(failure, "reason")
    assert record.terminal and record.failed
    assert ALLOWED_TRANSITIONS[record.status] == frozenset()
    with pytest.raises(LifecycleError):
        record.advance(ObservationStatus.HORIZON_REACHED)


def test_dataset_ready_is_terminal():
    record = observation(status=ObservationStatus.LABELED).advance(
        ObservationStatus.DATASET_READY)
    assert record.terminal and not record.failed


def test_fail_refuses_a_non_failure_state():
    with pytest.raises(LifecycleError, match="not a failure state"):
        observation(status=ObservationStatus.OBSERVING).fail(
            ObservationStatus.HORIZON_REACHED, "nope")


def test_a_transition_records_the_reason_and_the_time():
    record = observation(status=ObservationStatus.OBSERVING).fail(
        ObservationStatus.TIMEOUT, "NO_FUTURE_DATA", now=NOW)
    assert record.failure_reason == "NO_FUTURE_DATA"
    assert record.updated_at == NOW


def test_the_record_is_immutable():
    record = observation(status=ObservationStatus.OBSERVING)
    advanced = record.advance(ObservationStatus.HORIZON_REACHED)
    assert record.status is ObservationStatus.OBSERVING
    assert advanced is not record


# ------------------------------------------------------ 5. the record itself
def test_the_record_carries_every_documented_field():
    payload = observation().as_dict()
    for field in ("observation_id", "cycle_id", "symbol", "timestamp", "entry_price",
                  "direction", "strategy", "market_regime", "session", "feature_version",
                  "model_version", "nn_prediction", "nn_confidence", "risk_state",
                  "observation_horizon", "status"):
        assert field in payload, field


def test_the_deadline_is_the_horizon_after_the_timestamp():
    record = observation(horizon="4h")
    assert record.deadline == NOW + timedelta(hours=4)


def test_an_unknown_horizon_has_no_deadline():
    assert observation(horizon="7y").deadline is None


def test_the_horizon_is_not_reached_before_the_deadline():
    record = observation(horizon="1h")
    assert not record.horizon_reached(NOW + timedelta(minutes=59))
    assert record.horizon_reached(NOW + timedelta(minutes=60))


# ----------------------------------------------- building from a cycle result
def test_a_cycle_result_becomes_a_created_observation():
    result = FakeResult(cycle_id="c1", symbol="EURUSD", timestamp=NOW,
                        snapshot=snapshot(), regime=FakeRegime("BULL"))
    record = observation_from_cycle(result, horizon="1h", now=NOW)
    assert record.status is ObservationStatus.CREATED
    assert record.entry_price == pytest.approx(1.1000)
    assert record.market_regime == "BULL"
    assert record.session == "LONDON"
    assert record.nn_confidence == pytest.approx(0.80)
    assert record.risk_state == "APPROVED"


def test_a_cycle_that_reached_no_model_leaves_the_prediction_none():
    result = FakeResult(cycle_id="c2", symbol="EURUSD", timestamp=NOW, snapshot=None)
    record = observation_from_cycle(result, horizon="1h", now=NOW)
    assert record.nn_prediction is None
    assert record.nn_confidence is None
    assert record.entry_price is None


def test_the_cycle_id_can_be_overridden_for_determinism():
    result = FakeResult(cycle_id="random", symbol="EURUSD", timestamp=NOW,
                        snapshot=snapshot())
    record = observation_from_cycle(result, horizon="1h", now=NOW, cycle_id="fixed")
    assert record.cycle_id == "fixed"
    other = observation_from_cycle(result, horizon="1h", now=NOW, cycle_id="fixed")
    assert record.observation_id == other.observation_id


def test_a_blocked_risk_state_is_recorded_as_blocked():
    from dataclasses import replace

    blocked = replace(snapshot(), risk={"risk_allowed": False, "reason_codes": ["X"]})
    result = FakeResult(cycle_id="c3", symbol="EURUSD", timestamp=NOW, snapshot=blocked)
    assert observation_from_cycle(result, horizon="1h").risk_state == "BLOCKED"
