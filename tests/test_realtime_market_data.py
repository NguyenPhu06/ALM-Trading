"""Real-time tick and candle retrieval from MT5 (Phase 12 section 4)."""
from datetime import timedelta
from decimal import Decimal

import pytest

from tests.phase12_helpers import NOW, TIMEFRAMES, client


def test_tick_exposes_bid_ask_spread_and_timestamp():
    tick = client().get_tick("EURUSD").data
    assert tick["symbol"] == "EURUSD"
    assert tick["bid"] and tick["ask"] and tick["mid_price"]
    assert tick["spread"] == Decimal("0.00012")
    assert NOW - timedelta(seconds=5) <= tick["timestamp"] <= NOW


def test_tick_exposes_volume_when_the_feed_provides_it():
    tick = client().get_tick("EURUSD").data
    assert tick["tick_volume"] == Decimal("7")


def test_tick_carries_a_spread_state():
    tick = client().get_tick("EURUSD").data
    assert tick["spread_state"] in {"NORMAL", "ELEVATED", "EXTREME", "UNKNOWN"}


def test_candles_expose_full_ohlcv():
    candles = client().get_rates("EURUSD", "M15", 30).data
    last = candles[-1]
    for field in ("open", "high", "low", "close", "volume", "timestamp", "spread"):
        assert field in last, field
    assert last["source"] == "mt5"


def test_the_symbol_is_configurable_not_hardcoded():
    """A second symbol resolves through the same path with no code change."""
    connected = client(symbols=("EURUSDm", "GBPUSDm"))
    assert connected.get_tick("GBPUSD").ok
    assert connected.get_rates("GBPUSD", "M15", 10).ok


def test_an_unavailable_symbol_reports_rather_than_raising():
    result = client(symbols=("GBPUSDm",)).get_tick("EURUSD")
    assert not result.ok and result.code == "SYMBOL_NOT_FOUND"


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
def test_no_single_timeframe_is_hardcoded(timeframe):
    result = client().get_rates("EURUSD", timeframe, 20)
    assert result.ok and result.data
    assert result.data[-1]["timeframe"] == timeframe


def test_only_closed_candles_are_returned():
    candles = client().get_rates("EURUSD", "M15", 40).data
    assert all(row["is_closed"] for row in candles)
    assert all(row["timestamp"] + timedelta(minutes=15) <= NOW for row in candles)
