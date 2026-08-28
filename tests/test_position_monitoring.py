"""Open-position monitoring (section 23).

MAE and MFE only exist because something watched the position while it was open;
a broker never hands them back. Everything else here is arithmetic on top of a
read-only view: the monitor never modifies, closes or hedges anything.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from database.models import DemoPositionSnapshotRecord
from database.repositories.demo import DemoTradingRepository
from execution.demo.monitor import PositionMonitor
from tests.phase16_helpers import LONDON_MOMENT, live_context, order, service_for


def position(**overrides):
    payload = dict(ticket=700001, symbol="EURUSD", direction="BUY", volume=0.02,
                   open_price=1.1000, current_price=1.1000, profit=0.0, swap=0.0,
                   commission=0.0, stop_loss=1.0950, take_profit=1.1100,
                   open_time=LONDON_MOMENT)
    payload.update(overrides)
    return SimpleNamespace(**payload)


# --------------------------------------------------------------- excursions
def test_a_favourable_move_sets_the_mfe():
    monitor = PositionMonitor()
    snapshot = monitor.update(position(), current_price=1.1020)
    assert snapshot.mfe == pytest.approx(0.0020)
    assert snapshot.mae == pytest.approx(0.0)


def test_an_adverse_move_sets_the_mae():
    monitor = PositionMonitor()
    snapshot = monitor.update(position(), current_price=1.0980)
    assert snapshot.mae == pytest.approx(-0.0020)


def test_the_excursions_are_high_water_marks():
    """A recovery does not erase how far the trade went against you."""
    monitor = PositionMonitor()
    monitor.update(position(), current_price=1.0980)
    monitor.update(position(), current_price=1.1030)
    snapshot = monitor.update(position(), current_price=1.1000)
    assert snapshot.mae == pytest.approx(-0.0020)
    assert snapshot.mfe == pytest.approx(0.0030)


def test_a_short_position_measures_excursions_the_other_way():
    monitor = PositionMonitor()
    snapshot = monitor.update(position(direction="SELL"), current_price=1.0980)
    assert snapshot.mfe == pytest.approx(0.0020)
    assert snapshot.mae == pytest.approx(0.0)


# ----------------------------------------------------------------- distances
def test_the_stop_and_target_distances_are_tracked():
    monitor = PositionMonitor()
    snapshot = monitor.update(position(), current_price=1.1000)
    assert snapshot.sl_distance == pytest.approx(0.0050)
    assert snapshot.tp_distance == pytest.approx(0.0100)


def test_a_position_without_stops_reports_no_distances():
    monitor = PositionMonitor()
    snapshot = monitor.update(position(stop_loss=None, take_profit=None))
    assert snapshot.sl_distance is None and snapshot.tp_distance is None


def test_the_duration_grows():
    monitor = PositionMonitor()
    later = LONDON_MOMENT + timedelta(minutes=45)
    snapshot = monitor.update(position(), now=later)
    assert snapshot.duration_seconds == pytest.approx(2700.0)


# ------------------------------------------------------------------- context
def test_the_snapshot_carries_the_strategy_and_model_state():
    monitor = PositionMonitor()
    snapshot = monitor.update(position(), dca_levels=2, strategy_state="CHAMPION",
                              model_state="HEALTHY", spread=0.00012)
    assert snapshot.dca_levels == 2 and snapshot.strategy_state == "CHAMPION"
    assert snapshot.model_state == "HEALTHY" and snapshot.spread == 0.00012


def test_context_carries_forward_between_updates():
    monitor = PositionMonitor()
    monitor.update(position(), dca_levels=2, strategy_state="CHAMPION")
    snapshot = monitor.update(position(), current_price=1.1010)
    assert snapshot.dca_levels == 2 and snapshot.strategy_state == "CHAMPION"


def test_the_summary_aggregates_open_positions():
    monitor = PositionMonitor()
    monitor.update(position(ticket=1), current_price=1.1020)
    monitor.update(position(ticket=2, symbol="GBPUSD"), current_price=1.0980)
    summary = monitor.summary()
    assert summary["count"] == 2 and summary["symbols"] == ["EURUSD", "GBPUSD"]
    assert summary["worst_mae"] == pytest.approx(-0.0020)
    assert summary["best_mfe"] == pytest.approx(0.0020)


# -------------------------------------------------------------- the lifetime
def test_closing_a_ticket_returns_its_final_snapshot():
    monitor = PositionMonitor()
    monitor.update(position(), current_price=1.1020)
    final = monitor.close(700001)
    assert final is not None and final.mfe == pytest.approx(0.0020)
    assert monitor.get(700001) is None


def test_reconciling_drops_tickets_the_broker_no_longer_reports():
    monitor = PositionMonitor()
    monitor.update(position(ticket=1))
    monitor.update(position(ticket=2))
    gone = monitor.reconcile_open([1])
    assert [snapshot.ticket for snapshot in gone] == [2]
    assert monitor.get(1) is not None


def test_the_monitor_has_no_way_to_change_a_position():
    """Read-only by construction: no modify, close, reverse or hedge method."""
    for name in ("modify", "close_position", "set_sl_tp", "reverse", "hedge", "send_order"):
        assert not hasattr(PositionMonitor, name)


# -------------------------------------------------------------- persistence
def test_a_snapshot_persists(db_session):
    monitor = PositionMonitor()
    snapshot = monitor.update(position(), current_price=1.1020)
    DemoTradingRepository(db_session).save_position_snapshot(snapshot)
    row = db_session.query(DemoPositionSnapshotRecord).one()
    assert row.ticket == 700001 and row.mfe == pytest.approx(0.0020)


def test_a_filled_order_registers_its_position(db_session):
    service, _ = service_for(db_session)
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.executed
    snapshot = service.monitor.get(outcome.result.broker_ticket)
    assert snapshot is not None and snapshot.symbol == "EURUSD"
