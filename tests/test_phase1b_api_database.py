from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from database.repositories import CandleRepository, LiquidityEventRepository, StructureEventRepository
from features.pipeline import Phase1BPipeline


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def test_phase1b_event_repositories_and_api(client, db_session):
    common = {
        "event_timestamp": NOW, "confirmation_timestamp": NOW,
        "symbol": "EURUSD", "timeframe": "M15", "price": Decimal("1.1"),
        "strength": 55.0, "metadata_json": {}, "source": "test",
    }
    StructureEventRepository(db_session).add({**common, "event_type": "BULLISH_BOS", "direction": "BULLISH"})
    LiquidityEventRepository(db_session).add({**common, "event_type": "LIQUIDITY_LEVEL", "direction": "HIGH"})

    structure = client.get("/api/structure", params={"symbol": "EURUSD", "timeframe": "M15"})
    liquidity = client.get("/api/liquidity", params={"symbol": "EURUSD", "timeframe": "M15"})
    bias = client.get("/api/structure/bias", params={"symbol": "EURUSD", "timeframe": "M15"})
    assert structure.status_code == liquidity.status_code == bias.status_code == 200
    assert structure.json()["items"][0]["event_timestamp"]
    assert liquidity.json()["items"][0]["event_type"] == "LIQUIDITY_LEVEL"
    assert bias.json()["bias"] == "BULLISH"


def test_pipeline_reads_real_database_candles_and_is_idempotent(db_session):
    rows = [
        (1.10, 1.11, 1.09, 1.10),
        (1.10, 1.13, 1.10, 1.12),
        (1.12, 1.12, 1.08, 1.09),
        (1.09, 1.14, 1.09, 1.13),
        (1.13, 1.13, 1.09, 1.10),
    ]
    repository = CandleRepository(db_session)
    for index, (open_, high, low, close) in enumerate(rows):
        repository.add({
            "timestamp": NOW + timedelta(minutes=15 * index),
            "symbol": "EURUSD", "timeframe": "M15",
            "open": Decimal(str(open_)), "high": Decimal(str(high)),
            "low": Decimal(str(low)), "close": Decimal(str(close)),
            "volume": Decimal("1"), "source": "deterministic_fixture",
        })
    first = Phase1BPipeline(db_session).run("EURUSD", "M15")
    second = Phase1BPipeline(db_session).run("EURUSD", "M15")
    assert first["candles"] == 5
    assert first["liquidity_events_inserted"] > 0
    assert second["structure_events_inserted"] == 0
    assert second["liquidity_events_inserted"] == 0
