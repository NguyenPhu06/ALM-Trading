"""Restart safety (section 27).

    restart safely
    do not duplicate observations
    do not duplicate labels
    do not duplicate training data
    do not send orders
    resume from last completed cycle
"""
from datetime import datetime, timedelta, timezone

import pytest

from ai.dataset.labels import LabelingEngine
from database.repositories.forward import ForwardObservationRepository
from observation.driver import DriverConfig, ObservationDriver, TickOutcome
from observation.ingestion import DatasetIngestor, IngestionRefusal
from observation.lifecycle import ObservationStatus
from observation.outcome import ForwardOutcomeEngine
from tests.phase14_helpers import (
    NOW,
    FakeCycle,
    MemoryRepository,
    candle_loader,
    candles,
    observation,
    outcome,
)

CANDLE = datetime(2026, 8, 28, 9, 30, tzinfo=timezone.utc)


def driver(repository, *, clock=None, ingestor=None, rows=(), cycle_time=NOW):
    return ObservationDriver(
        cycle=FakeCycle(timestamp=cycle_time), repository=repository,
        config=DriverConfig(interval_seconds=300, symbols=("EURUSD",), horizon="1h"),
        outcome_engine=ForwardOutcomeEngine(labeler=LabelingEngine()),
        candles=candle_loader(rows) if rows else None, ingestor=ingestor,
        clock=clock or (lambda: NOW), sleeper=lambda seconds: None)


# ---------------------------------------------------- resuming after a crash
def test_a_restart_reloads_the_cycles_it_already_ran(memory_repository):
    first = driver(memory_repository)
    first.run_once(now=CANDLE)

    # A brand-new driver object, as after a process restart.
    second = driver(memory_repository)
    assert second.stats.seen_cycles == set()
    assert second.resume() == 1
    assert second.stats.seen_cycles


def test_a_restart_does_not_re_observe_the_same_candle(memory_repository):
    driver(memory_repository).run_once(now=CANDLE)
    restarted = driver(memory_repository)
    restarted.start()
    tick = restarted.run_once(now=CANDLE + timedelta(seconds=45))
    assert tick.cycles[0].outcome is TickOutcome.DUPLICATE
    assert len(memory_repository.observations) == 1


def test_a_restart_without_the_in_memory_cache_still_detects_duplicates(memory_repository):
    """Recovery must not depend on the process that wrote the row."""
    driver(memory_repository).run_once(now=CANDLE)
    restarted = driver(memory_repository)
    restarted.stats.seen_cycles.clear()
    assert restarted.run_once(now=CANDLE).cycles[0].outcome is TickOutcome.DUPLICATE


def test_a_restart_picks_up_the_next_candle(memory_repository):
    driver(memory_repository).run_once(now=CANDLE)
    restarted = driver(memory_repository)
    restarted.start()
    tick = restarted.run_once(now=CANDLE + timedelta(minutes=5))
    assert tick.cycles[0].outcome is TickOutcome.EXECUTED


def test_resume_is_a_no_op_without_a_repository():
    assert driver(None).resume() == 0


def test_a_broken_repository_does_not_stop_the_resume():
    class Broken(MemoryRepository):
        def known_cycle_ids(self, limit=5000):
            raise RuntimeError("database down")

    assert driver(Broken()).resume() == 0


def test_a_broken_duplicate_check_does_not_stop_the_tick():
    class Broken(MemoryRepository):
        def observation_exists(self, *, cycle_id=None, observation_id=None):
            raise RuntimeError("lookup failed")

    tick = driver(Broken()).run_once(now=CANDLE)
    assert tick.cycles[0].outcome is TickOutcome.EXECUTED


# ------------------------------------------------------- no duplicate labels
def test_an_already_resolved_observation_is_not_resolved_twice(memory_repository):
    rows = candles(20, start=NOW, step_minutes=5)
    ingestor = DatasetIngestor(memory_repository)
    later = NOW + timedelta(hours=1, minutes=5)

    # The tick's own new observation is stamped `later`, so its horizon has not
    # elapsed and only the pre-existing one is due.
    instance = driver(memory_repository, clock=lambda: later, ingestor=ingestor, rows=rows,
                      cycle_time=later)
    memory_repository.save_observation(observation(1, timestamp=NOW))
    first = instance.run_once(now=later)
    assert len(first.resolved) == 1

    # Second pass: the observation is no longer OBSERVING, so it is not due.
    second = instance.run_once(now=later + timedelta(minutes=5))
    assert second.resolved == ()
    assert len(memory_repository.labels) == 1


def test_a_resolved_observation_reaches_dataset_ready(memory_repository):
    rows = candles(20, start=NOW, step_minutes=5)
    later = NOW + timedelta(hours=1, minutes=5)
    instance = driver(memory_repository, clock=lambda: later, cycle_time=later,
                      ingestor=DatasetIngestor(memory_repository), rows=rows)
    memory_repository.save_observation(observation(2, timestamp=NOW))
    instance.run_once(now=later)
    assert (memory_repository.observations["obs-2"].status
            is ObservationStatus.DATASET_READY)


def test_re_ingesting_the_same_row_is_refused(memory_repository):
    from tests.phase14_helpers import observation as make

    record = make(3, status=ObservationStatus.LABELED)
    resolved = outcome(3)
    label = LabelingEngine().label(
        entry_price=1.1, entry_time=NOW, horizon="1h",
        future=candles(20, start=NOW, step_minutes=5),
        now=NOW + timedelta(hours=2)).label
    from dataclasses import replace

    resolved = replace(resolved, label=label)

    ingestor = DatasetIngestor(memory_repository)
    assert ingestor.ingest(record, resolved).accepted
    # A fresh ingestor, as after a restart: the repository is the source of truth.
    restarted = DatasetIngestor(memory_repository)
    assert restarted.ingest(record, resolved).refusal is IngestionRefusal.DUPLICATE_ROW


# ------------------------------------------------------- database durability
def test_observations_survive_a_new_repository_object(db_session):
    first = ForwardObservationRepository(db_session)
    first.save_observation(observation(4))
    second = ForwardObservationRepository(db_session)
    assert second.observation_exists(cycle_id="cycle-4")
    assert second.known_cycle_ids() == ["cycle-4"]


def test_a_resolved_outcome_is_written_once(db_session):
    repository = ForwardObservationRepository(db_session)
    record = observation(5)
    repository.save_outcome(record, outcome(5))
    repository.save_outcome(record, outcome(5))
    assert len(repository.recent_outcomes(10)) == 1


def test_the_due_query_only_returns_open_observations(db_session):
    repository = ForwardObservationRepository(db_session)
    repository.save_observation(observation(6, status=ObservationStatus.OBSERVING))
    repository.save_observation(observation(7, status=ObservationStatus.DATASET_READY))
    due = repository.observations_due(now=NOW + timedelta(hours=2))
    assert [item.observation_id for item in due] == ["obs-6"]


def test_a_reloaded_observation_can_be_compared_against_an_aware_now(db_session):
    """SQLite returns naive datetimes; the repository re-attaches UTC on read."""
    repository = ForwardObservationRepository(db_session)
    repository.save_observation(observation(9, status=ObservationStatus.OBSERVING))
    reloaded = repository.observations_due(now=NOW + timedelta(hours=2))[0]
    assert reloaded.timestamp.tzinfo is not None
    assert reloaded.horizon_reached(NOW + timedelta(hours=2))


def test_the_due_query_ignores_observations_whose_horizon_has_not_elapsed(db_session):
    repository = ForwardObservationRepository(db_session)
    repository.save_observation(observation(8, status=ObservationStatus.OBSERVING))
    assert repository.observations_due(now=NOW + timedelta(minutes=10)) == []


# ------------------------------------------------------------ never trades
def test_no_restart_path_sends_an_order(memory_repository):
    instance = driver(memory_repository)
    instance.resume()
    tick = instance.run_once(now=CANDLE)
    assert tick.orders_sent == 0
    assert instance.status(CANDLE)["orders_sent"] == 0
