"""Forward observation performance records (section 31)."""
from datetime import datetime, timedelta, timezone

import pytest

from ai.dataset.labels import LabelingEngine
from database.models import ObservationPerformanceRecord
from database.repositories import LearningRepository, ObservationRepository
from tests.phase13_helpers import NOW, candles

REQUIRED = ("observation_id", "entry", "future_price", "future_return", "mfe", "mae",
            "hypothetical_pnl", "duration_seconds", "spread", "session", "regime",
            "nn_probability", "nn_confidence", "strategy_decision", "dca_state")


def test_the_table_carries_every_documented_field():
    columns = {column.name for column in ObservationPerformanceRecord.__table__.columns}
    for name in REQUIRED:
        assert name in columns, name


def test_a_performance_row_persists(db_session):
    repository = ObservationRepository(db_session)
    row = repository.save_performance({
        "cycle_id": "c1", "observation_id": "o1", "symbol": "EURUSD", "signal": "BUY",
        "entry": 1.1000, "opened_at": NOW, "session": "LONDON", "regime": "BULL",
        "nn_confidence": 0.72, "strategy_confidence": 0.65, "dca_state": "NONE",
        "spread": 0.00012,
    })
    assert row.id and row.observed is True


def test_a_row_is_forward_observation_not_a_backtest(db_session):
    repository = ObservationRepository(db_session)
    row = repository.save_performance({"cycle_id": "c1", "symbol": "EURUSD",
                                       "signal": "BUY", "entry": 1.1, "opened_at": NOW})
    assert row.observed is True
    assert "backtest" not in str(row.record_json).lower()


def test_a_label_attaches_to_an_existing_observation(db_session):
    observation = ObservationRepository(db_session)
    observation.save_performance({
        "cycle_id": "c1", "observation_id": "obs-1", "symbol": "EURUSD", "signal": "BUY",
        "entry": 1.1000, "opened_at": NOW - timedelta(hours=4)})

    entry_time = NOW - timedelta(hours=4)
    label = LabelingEngine().label(
        entry_price=1.1000, entry_time=entry_time,
        future=candles(24, start=entry_time, step_minutes=5, drift=0.00015),
        horizon="1h", spread=0.00010, now=NOW).label

    row = LearningRepository(db_session).attach_label("obs-1", label)
    assert row is not None
    assert row.future_return == pytest.approx(label.future_return)
    assert row.future_price == pytest.approx(label.future_price)
    assert row.mfe == pytest.approx(label.future_mfe)
    assert row.mae == pytest.approx(label.future_mae)
    assert row.hypothetical_pnl == pytest.approx(label.net_return)
    assert row.horizon == "1h" and row.label_version == "labels_v1"


def test_attaching_to_an_unknown_observation_returns_none(db_session):
    entry_time = NOW - timedelta(hours=4)
    label = LabelingEngine().label(
        entry_price=1.1, entry_time=entry_time,
        future=candles(24, start=entry_time, step_minutes=5), horizon="1h", now=NOW).label
    assert LearningRepository(db_session).attach_label("missing", label) is None


def test_unlabelled_observations_are_listed(db_session):
    observation = ObservationRepository(db_session)
    for index in range(3):
        observation.save_performance({
            "cycle_id": f"c{index}", "observation_id": f"obs-{index}", "symbol": "EURUSD",
            "signal": "BUY", "entry": 1.1, "opened_at": NOW - timedelta(hours=index)})
    learning = LearningRepository(db_session)
    assert len(learning.unlabelled_observations()) == 3
    assert learning.labelled_count() == 0


def test_labelled_rows_are_counted(db_session):
    observation = ObservationRepository(db_session)
    observation.save_performance({"cycle_id": "c1", "observation_id": "obs-1",
                                  "symbol": "EURUSD", "signal": "BUY", "entry": 1.1,
                                  "opened_at": NOW - timedelta(hours=4)})
    entry_time = NOW - timedelta(hours=4)
    label = LabelingEngine().label(
        entry_price=1.1, entry_time=entry_time,
        future=candles(24, start=entry_time, step_minutes=5, drift=0.0001),
        horizon="1h", now=NOW).label
    learning = LearningRepository(db_session)
    learning.attach_label("obs-1", label)
    assert learning.labelled_count() == 1
    assert learning.unlabelled_observations() == []
