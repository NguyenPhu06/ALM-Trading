from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import text

from database.repositories import CandleRepository, COTRepository, TradingViewAlertRepository


def candle_values() -> dict:
    return {
        "timestamp": datetime(2026, 8, 24, 8, 0, tzinfo=timezone.utc),
        "symbol": "EURUSD", "timeframe": "M15", "open": Decimal("1.10"),
        "high": Decimal("1.11"), "low": Decimal("1.09"), "close": Decimal("1.105"),
        "volume": Decimal("100"), "source": "test",
    }


def test_database_connection_and_candle_duplicate(db_session):
    assert db_session.execute(text("SELECT 1")).scalar_one() == 1
    repository = CandleRepository(db_session)
    candle, created = repository.add(candle_values())
    assert created and candle is not None
    duplicate, created = repository.add(candle_values())
    assert not created and duplicate is None
    assert len(repository.list(symbol="EURUSD", timeframe="M15")) == 1
    assert repository.latest("EURUSD", "M15").id == candle.id


def test_cot_insert_update_and_retrieval(db_session):
    values = {
        "report_date": date(2026, 8, 18), "market": "EURO FX - CME",
        "contract": "099741", "source": "cftc_tff", "dealer_long": 10,
        "dealer_short": 20, "dealer_spread": 3, "asset_manager_long": 30,
        "asset_manager_short": 15, "asset_manager_spread": 4,
        "leveraged_money_long": 12, "leveraged_money_short": 25,
        "leveraged_money_spread": 2, "other_reportables_long": 5,
        "other_reportables_short": 6, "other_reportables_spread": 1,
        "non_reportables_long": 8, "non_reportables_short": 7,
        "non_reportables_spread": None, "open_interest": 1000,
        "raw_data_json": {"source": "test"},
    }
    repository = COTRepository(db_session)
    report, created = repository.upsert(values)
    assert created and report.open_interest == 1000
    values["open_interest"] = 1001
    report, created = repository.upsert(values)
    assert not created and report.open_interest == 1001
    assert repository.list(market="EURO")[0].id == report.id


def test_webhook_repository_insert(db_session):
    values = {
        "received_at": datetime.now(timezone.utc),
        "event_timestamp": datetime.now(timezone.utc),
        "symbol": "EURUSD", "timeframe": "M15", "event_type": "BOS",
        "direction": "BULLISH", "price": Decimal("1.1"),
        "payload_json": {"event": "BOS"}, "source": "tradingview",
    }
    repository = TradingViewAlertRepository(db_session)
    alert = repository.add(values)
    assert repository.list(symbol="EURUSD")[0].id == alert.id

