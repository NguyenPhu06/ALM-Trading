"""The feature snapshot: a complete record of one analysis cycle."""
import pytest

from observation.snapshot import FeatureSnapshot, MarketSnapshot, jsonable, new_cycle_id
from tests.phase12_helpers import cycle_for
from tests.phase9_helpers import StubInference

REQUIRED_SECTIONS = (
    "market_data", "timeframes", "structure", "liquidity", "indicators", "session",
    "regime", "spread", "volatility", "neural_network", "strategy", "risk",
    "data_quality", "execution_simulation",
)


@pytest.fixture()
def snapshot(db_session):
    result = cycle_for(db_session, inference=StubInference()).run("EURUSD")
    assert result.snapshot is not None
    return result.snapshot


def test_the_snapshot_contains_every_required_section(snapshot):
    payload = snapshot.as_dict()
    for section in REQUIRED_SECTIONS:
        assert section in payload, section


def test_the_snapshot_identifies_its_cycle_and_symbol(snapshot):
    assert snapshot.cycle_id and snapshot.symbol == "EURUSD"
    assert snapshot.timestamp is not None
    assert snapshot.feature_version == "phase12.features.v1"
    assert snapshot.source == "mt5"


def test_market_data_records_the_live_quote(snapshot):
    market = snapshot.as_dict()["market_data"]
    assert market["bid"] and market["ask"] and market["mid_price"]
    assert market["source"] == "mt5"


def test_every_timeframe_is_recorded_with_its_quality(snapshot):
    timeframes = snapshot.as_dict()["timeframes"]
    assert set(timeframes) == {"D1", "H4", "H1", "M30", "M15", "M5"}
    for name, detail in timeframes.items():
        assert detail["candles"] > 0, name
        assert detail["last_candle"] is not None, name
        assert detail["quality"] is not None, name


def test_structure_and_indicators_are_recorded_per_timeframe(snapshot):
    payload = snapshot.as_dict()
    assert payload["structure"] and payload["indicators"]
    assert "M15" in payload["structure"] and "M15" in payload["indicators"]


def test_the_neural_output_is_recorded_when_a_model_ran(snapshot):
    nn = snapshot.as_dict()["neural_network"]
    assert nn and nn["prob_up"] and nn["model_version"] and nn["feature_version"]


def test_the_execution_simulation_is_part_of_the_record(snapshot):
    simulation = snapshot.as_dict()["execution_simulation"]
    assert simulation["orders_sent"] == 0
    assert simulation["execution"] in {"BLOCKED", "NOT_APPLICABLE"}


def test_the_snapshot_is_json_safe(snapshot):
    import json

    json.dumps(snapshot.as_dict())


def test_jsonable_converts_datetimes_decimals_and_enums():
    from datetime import datetime, timezone
    from decimal import Decimal
    from enum import StrEnum

    class Kind(StrEnum):
        A = "A"

    payload = jsonable({"t": datetime(2026, 8, 27, tzinfo=timezone.utc),
                        "d": Decimal("1.5"), "e": Kind.A, "nested": [Decimal("2")]})
    assert payload["t"].startswith("2026-08-27")
    assert payload["d"] == 1.5 and payload["e"] == "A" and payload["nested"] == [2.0]


def test_a_market_snapshot_is_derived_from_the_feature_snapshot(db_session):
    result = cycle_for(db_session, inference=StubInference()).run("EURUSD")
    market = result.market.as_dict()
    assert market["symbol"] == "EURUSD" and market["cycle_id"] == result.cycle_id
    for section in ("price", "spread", "sessions", "regime", "timeframes", "structure",
                    "liquidity", "indicators", "strategy", "risk", "execution"):
        assert section in market, section


def test_snapshots_are_persisted_for_future_training(db_session):
    from database.models import FeatureSnapshotRecord, ObservationMarketSnapshotRecord
    from database.repositories import ObservationRepository

    repository = ObservationRepository(db_session)
    cycle_for(db_session, inference=StubInference(), repository=repository).run("EURUSD")
    assert db_session.query(FeatureSnapshotRecord).count() == 1
    assert db_session.query(ObservationMarketSnapshotRecord).count() == 1

    row = db_session.query(FeatureSnapshotRecord).one()
    assert row.symbol == "EURUSD" and row.feature_version == "phase12.features.v1"
    assert row.snapshot_json["market_data"]["source"] == "mt5"


def test_a_new_cycle_id_is_unique():
    assert new_cycle_id() != new_cycle_id()
