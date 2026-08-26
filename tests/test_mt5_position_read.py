"""Positions are readable and classified; nothing is ever modified."""
from datetime import datetime, timezone

from database.models import MT5PositionSnapshotRecord
from execution.mt5.positions import (
    MT5Position,
    PositionDirection,
    PositionOwnership,
    PositionReader,
)
from execution.mt5.service import MT5ReadOnlyService
from tests.phase10_helpers import ALM_POSITION, EXTERNAL_POSITION, connected_client, positions


def client_with(*rows):
    return connected_client(positions=positions(*rows))


def test_every_documented_position_field_is_read():
    position = client_with(EXTERNAL_POSITION).get_positions().data[0]
    assert position.ticket == 600001 and position.symbol == "EURUSD"
    assert position.direction is PositionDirection.LONG
    assert position.volume == 0.10 and position.open_price == 1.09950
    assert position.current_price == 1.10012
    assert position.stop_loss == 1.09500 and position.take_profit == 1.10500
    assert position.profit == 6.20 and position.swap == -0.15 and position.commission == -0.80
    assert position.open_time == datetime(2026, 8, 26, 8, tzinfo=timezone.utc)
    assert position.magic_number == 0 and position.comment == "manual entry"


def test_a_manual_position_is_external():
    position = client_with(EXTERNAL_POSITION).get_positions().data[0]
    assert position.ownership is PositionOwnership.EXTERNAL and position.is_external


def test_an_alm_commented_position_is_recognised():
    position = client_with(ALM_POSITION).get_positions().data[0]
    assert position.ownership is PositionOwnership.ALM and not position.is_external


def test_a_matching_magic_number_marks_a_position_as_alm():
    reader = PositionReader(alm_magic_number=4242)
    assert reader.classify(4242, "") is PositionOwnership.ALM
    assert reader.classify(1111, "") is PositionOwnership.EXTERNAL


def test_magic_number_zero_never_means_alm():
    """Zero is the MetaTrader default for manual trades; claiming it would be wrong."""
    reader = PositionReader(alm_magic_number=0)
    assert reader.classify(0, "manual") is PositionOwnership.EXTERNAL


def test_short_positions_are_read_correctly():
    position = client_with({**EXTERNAL_POSITION, "type": 1}).get_positions().data[0]
    assert position.direction is PositionDirection.SHORT


def test_absent_stop_loss_and_take_profit_read_as_none():
    position = client_with({**EXTERNAL_POSITION, "sl": 0, "tp": 0}).get_positions().data[0]
    assert position.stop_loss is None and position.take_profit is None


def test_positions_are_reported_under_canonical_symbols():
    position = client_with(EXTERNAL_POSITION).get_positions().data[0]
    assert position.symbol == "EURUSD"


def test_the_summary_separates_alm_from_external():
    client = connected_client(positions=positions(EXTERNAL_POSITION, ALM_POSITION))
    summary = PositionReader.summarize(client.get_positions().data)
    assert summary["count"] == 2 and summary["alm"] == 1 and summary["external"] == 1
    assert summary["symbols"] == ["EURUSD"]


def test_positions_are_persisted_as_read_only_snapshots(db_session):
    client = connected_client(positions=positions(EXTERNAL_POSITION, ALM_POSITION))
    MT5ReadOnlyService(db_session, client=client).sync_positions()
    rows = db_session.query(MT5PositionSnapshotRecord).all()
    assert len(rows) == 2
    assert {row.ownership for row in rows} == {"EXTERNAL", "ALM"}
    assert all(row.symbol == "EURUSD" for row in rows)


def test_the_position_model_has_no_mutation_method():
    for name in ("close", "modify", "reverse", "hedge", "dca", "set_sl", "set_tp"):
        assert not hasattr(MT5Position, name), name
    for name in ("close", "modify", "reverse", "hedge", "place_dca"):
        assert not hasattr(PositionReader, name), name


def test_empty_position_list_is_not_an_error():
    result = connected_client().get_positions()
    assert result.ok and result.data == []
