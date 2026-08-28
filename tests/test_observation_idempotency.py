"""A cycle must not execute twice for the same symbol/timeframe/candle (section 3)."""
from datetime import datetime, timedelta, timezone

import pytest

from database.repositories.forward import ForwardObservationRepository
from observation.driver import (
    DriverConfig,
    ObservationDriver,
    TickOutcome,
    deterministic_cycle_id,
)
from observation.lifecycle import deterministic_observation_id
from tests.phase14_helpers import NOW, FakeCycle

CANDLE = datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc)


def driver(repository=None, **kwargs):
    kwargs.setdefault("cycle", FakeCycle(timestamp=NOW))
    kwargs.setdefault("config", DriverConfig(interval_seconds=300, symbols=("EURUSD",)))
    return ObservationDriver(repository=repository, clock=lambda: NOW,
                             sleeper=lambda seconds: None, **kwargs)


# ------------------------------------------------------- deterministic ids
def test_the_same_inputs_always_produce_the_same_cycle_id():
    assert (deterministic_cycle_id("EURUSD", "M5", CANDLE)
            == deterministic_cycle_id("EURUSD", "M5", CANDLE))


def test_a_different_symbol_produces_a_different_cycle_id():
    assert (deterministic_cycle_id("EURUSD", "M5", CANDLE)
            != deterministic_cycle_id("GBPUSD", "M5", CANDLE))


def test_a_different_timeframe_produces_a_different_cycle_id():
    assert (deterministic_cycle_id("EURUSD", "M5", CANDLE)
            != deterministic_cycle_id("EURUSD", "M15", CANDLE))


def test_a_different_candle_produces_a_different_cycle_id():
    assert (deterministic_cycle_id("EURUSD", "M5", CANDLE)
            != deterministic_cycle_id("EURUSD", "M5", CANDLE + timedelta(minutes=5)))


def test_the_cycle_id_is_case_insensitive_on_symbol_and_timeframe():
    assert (deterministic_cycle_id("eurusd", "m5", CANDLE)
            == deterministic_cycle_id("EURUSD", "M5", CANDLE))


def test_the_cycle_id_survives_a_timezone_change():
    """A candle expressed in another zone is the same candle."""
    elsewhere = CANDLE.astimezone(timezone(timedelta(hours=7)))
    assert (deterministic_cycle_id("EURUSD", "M5", elsewhere)
            == deterministic_cycle_id("EURUSD", "M5", CANDLE))


def test_the_observation_id_is_derived_from_the_cycle_id():
    cycle_id = deterministic_cycle_id("EURUSD", "M5", CANDLE)
    assert (deterministic_observation_id(cycle_id, "EURUSD", "1h")
            == deterministic_observation_id(cycle_id, "EURUSD", "1h"))
    assert (deterministic_observation_id(cycle_id, "EURUSD", "1h")
            != deterministic_observation_id(cycle_id, "EURUSD", "4h"))


# ------------------------------------------------------- duplicate cycles
def test_a_second_tick_in_the_same_candle_is_a_duplicate(memory_repository):
    instance = driver(memory_repository)
    first = instance.run_once(now=CANDLE + timedelta(seconds=10))
    second = instance.run_once(now=CANDLE + timedelta(seconds=200))
    assert first.cycles[0].outcome is TickOutcome.EXECUTED
    assert second.cycles[0].outcome is TickOutcome.DUPLICATE
    assert len(memory_repository.observations) == 1


def test_a_duplicate_does_not_re_run_the_cycle(memory_repository):
    cycle = FakeCycle(timestamp=NOW)
    instance = driver(memory_repository, cycle=cycle)
    instance.run_once(now=CANDLE)
    instance.run_once(now=CANDLE + timedelta(seconds=60))
    assert cycle.calls == ["EURUSD"]


def test_the_next_candle_is_not_a_duplicate(memory_repository):
    instance = driver(memory_repository)
    instance.run_once(now=CANDLE)
    tick = instance.run_once(now=CANDLE + timedelta(minutes=5))
    assert tick.cycles[0].outcome is TickOutcome.EXECUTED
    assert len(memory_repository.observations) == 2


def test_duplicates_are_counted_separately(memory_repository):
    instance = driver(memory_repository)
    instance.run_once(now=CANDLE)
    instance.run_once(now=CANDLE + timedelta(seconds=30))
    assert instance.stats.cycles_executed == 1
    assert instance.stats.cycles_duplicate == 1


def test_a_duplicate_is_ignored_safely_not_raised(memory_repository):
    instance = driver(memory_repository)
    instance.run_once(now=CANDLE)
    tick = instance.run_once(now=CANDLE)  # must not raise
    assert tick.cycles[0].reasons == ("DUPLICATE_CYCLE",)


# ------------------------------------------------- database-backed identity
def test_the_repository_enforces_one_row_per_cycle(db_session):
    from tests.phase14_helpers import observation

    repository = ForwardObservationRepository(db_session)
    record = observation(1)
    repository.save_observation(record)
    repository.save_observation(record)  # upsert, not insert
    assert len(repository.recent_observations(10)) == 1


def test_observation_exists_answers_by_cycle_id(db_session):
    from tests.phase14_helpers import observation

    repository = ForwardObservationRepository(db_session)
    repository.save_observation(observation(2))
    assert repository.observation_exists(cycle_id="cycle-2")
    assert not repository.observation_exists(cycle_id="cycle-999")


def test_saving_the_same_observation_twice_keeps_the_latest_status(db_session):
    from observation.lifecycle import ObservationStatus
    from tests.phase14_helpers import observation

    repository = ForwardObservationRepository(db_session)
    record = observation(3, status=ObservationStatus.OBSERVING)
    repository.save_observation(record)
    repository.save_observation(record.advance(ObservationStatus.HORIZON_REACHED))
    rows = repository.recent_observations(10)
    assert len(rows) == 1 and rows[0].status == "HORIZON_REACHED"


def test_two_symbols_in_the_same_candle_are_not_duplicates(memory_repository):
    instance = driver(memory_repository,
                      config=DriverConfig(interval_seconds=300,
                                          symbols=("EURUSD", "GBPUSD")))
    tick = instance.run_once(now=CANDLE)
    assert len(tick.executed) == 2
    assert len({report.cycle_id for report in tick.cycles}) == 2
