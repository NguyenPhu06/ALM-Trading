"""Invalid MT5 data never reaches the strategy."""
from datetime import timedelta

import pytest

from data_sources.validators import QualityStatus
from execution.mt5.quality import (
    DATA_QUALITY_ERROR, DUPLICATE_TIMESTAMP, MT5DataQualityGate, NON_POSITIVE_PRICE,
    STALE_TICK, TIMEFRAME_MISALIGNED, UNKNOWN_SYMBOL,
)
from execution.mt5.service import MT5ReadOnlyService
from database.models import MT5DataQualityEventRecord
from tests.phase10_helpers import NOW, connected_client


def candle(**overrides):
    row = {"timestamp": NOW - timedelta(minutes=15), "symbol": "EURUSD", "timeframe": "M15",
           "open": 1.1, "high": 1.2, "low": 1.0, "close": 1.15, "volume": 10,
           "spread": 0.0001, "is_closed": True, "source": "mt5"}
    row.update(overrides)
    return row


def gate():
    return MT5DataQualityGate(known_symbols=("EURUSD", "GBPUSD"))


def test_clean_candles_pass():
    outcome = gate().evaluate_candles([candle()], symbol="EURUSD", timeframe="M15", as_of=NOW)
    assert outcome.status is QualityStatus.VALID and outcome.valid
    assert outcome.accepted and outcome.code == "OK"


@pytest.mark.parametrize("price_field", ["open", "high", "low", "close"])
def test_non_positive_prices_are_rejected(price_field):
    outcome = gate().evaluate_candles([candle(**{price_field: 0})], symbol="EURUSD",
                                      timeframe="M15", as_of=NOW)
    assert outcome.status is QualityStatus.INVALID
    assert NON_POSITIVE_PRICE in outcome.reasons
    assert outcome.accepted == () and outcome.code == DATA_QUALITY_ERROR


def test_negative_prices_are_rejected():
    outcome = gate().evaluate_candles([candle(low=-1.0)], symbol="EURUSD", timeframe="M15", as_of=NOW)
    assert outcome.status is QualityStatus.INVALID and NON_POSITIVE_PRICE in outcome.reasons


def test_duplicate_timestamps_are_rejected():
    outcome = gate().evaluate_candles([candle(), candle()], symbol="EURUSD",
                                      timeframe="M15", as_of=NOW)
    assert outcome.status is QualityStatus.INVALID and DUPLICATE_TIMESTAMP in outcome.reasons


def test_misaligned_timestamps_are_flagged():
    misaligned = candle(timestamp=NOW - timedelta(minutes=15, seconds=7))
    outcome = gate().evaluate_candles([misaligned], symbol="EURUSD", timeframe="M15", as_of=NOW)
    assert TIMEFRAME_MISALIGNED in outcome.reasons


def test_an_unknown_symbol_is_rejected():
    outcome = gate().evaluate_candles([candle(symbol="ZZZZZZ")], symbol="ZZZZZZ",
                                      timeframe="M15", as_of=NOW)
    assert outcome.status is QualityStatus.INVALID and UNKNOWN_SYMBOL in outcome.reasons


def test_ohlc_inconsistency_is_rejected():
    outcome = gate().evaluate_candles([candle(high=1.0, low=1.2)], symbol="EURUSD",
                                      timeframe="M15", as_of=NOW)
    assert outcome.status is QualityStatus.INVALID


def test_no_data_is_rejected():
    outcome = gate().evaluate_candles([], symbol="EURUSD", timeframe="M15", as_of=NOW)
    assert outcome.status is QualityStatus.INVALID and "NO_DATA" in outcome.reasons


def test_a_fresh_tick_passes_and_a_stale_one_is_flagged():
    fresh = {"symbol": "EURUSD", "bid": 1.1, "ask": 1.1002, "timestamp": NOW - timedelta(seconds=2)}
    stale = {**fresh, "timestamp": NOW - timedelta(minutes=10)}
    assert gate().evaluate_tick(fresh, as_of=NOW).status is QualityStatus.VALID
    outcome = gate().evaluate_tick(stale, as_of=NOW)
    assert STALE_TICK in outcome.reasons


def test_a_non_positive_tick_price_is_rejected():
    bad = {"symbol": "EURUSD", "bid": 0, "ask": 1.1, "timestamp": NOW}
    outcome = gate().evaluate_tick(bad, as_of=NOW)
    assert outcome.status is QualityStatus.INVALID and not outcome.accepted


def test_the_service_records_a_quality_event_per_timeframe(db_session):
    service = MT5ReadOnlyService(db_session, client=connected_client())
    service.sync_market_data("EURUSD", count=40)
    rows = db_session.query(MT5DataQualityEventRecord).all()
    assert {row.timeframe for row in rows} == {"D1", "H4", "H1", "M30", "M15", "M5"}
    assert all(row.status == "VALID" and row.source == "mt5" for row in rows)


def test_invalid_candles_contribute_nothing_downstream(db_session):
    service = MT5ReadOnlyService(db_session, client=connected_client())
    service.gate = MT5DataQualityGate(known_symbols=("NOTHING",))
    outcome = service.sync_market_data("EURUSD", count=20)
    assert outcome.code == "NO_MARKET_DATA"
    assert set(outcome.timeframes.values()) == {0}
