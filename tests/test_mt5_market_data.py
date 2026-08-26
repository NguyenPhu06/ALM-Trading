"""Ticks, spread monitoring and candle normalization."""
from datetime import timedelta
from decimal import Decimal

import pytest

from execution.mt5.market_data import (
    MT5_SOURCE, MT5MarketDataReader, SpreadMonitor, SpreadState, mt5_timeframe,
)
from tests.phase10_helpers import NOW, connected_client, module


def test_tick_carries_bid_ask_last_spread_and_timestamp():
    tick = connected_client().get_tick("EURUSD").data
    assert tick["symbol"] == "EURUSD"
    assert tick["bid"] == Decimal("1.10012") and tick["ask"] == Decimal("1.10024")
    assert tick["last"] == pytest.approx(1.10018)
    assert tick["spread"] == Decimal("0.00012")
    assert tick["mid_price"] == Decimal("1.10018")
    assert tick["source"] == MT5_SOURCE
    # MT5 tick time is whole epoch seconds, so a sub-second age truncates.
    assert NOW - timedelta(seconds=2) <= tick["timestamp"] <= NOW
    assert tick["tick_volume"] == Decimal("7")


def test_tick_is_reported_under_the_canonical_symbol_not_the_broker_name():
    tick = connected_client(symbols=("EURUSDm",)).get_tick("EURUSD").data
    assert tick["symbol"] == "EURUSD"


def test_an_unknown_symbol_yields_a_clear_code():
    result = connected_client(symbols=("GBPUSDm",)).get_tick("EURUSD")
    assert not result.ok and result.code == "SYMBOL_NOT_FOUND"


def test_candles_carry_the_full_alm_schema():
    candle = connected_client().get_rates("EURUSD", "M15", 10).data[-1]
    for field in ("timestamp", "open", "high", "low", "close", "volume", "spread",
                  "symbol", "timeframe", "source", "is_closed"):
        assert field in candle, field
    assert candle["symbol"] == "EURUSD" and candle["timeframe"] == "M15"
    assert candle["source"] == MT5_SOURCE and candle["is_closed"] is True


def test_only_closed_candles_are_returned():
    candles = connected_client().get_rates("EURUSD", "M15", 20).data
    assert all(candle["is_closed"] for candle in candles)
    assert all(candle["timestamp"] + timedelta(minutes=15) <= NOW for candle in candles)


def test_candles_are_returned_in_chronological_order():
    candles = connected_client().get_rates("EURUSD", "H1", 20).data
    stamps = [candle["timestamp"] for candle in candles]
    assert stamps == sorted(stamps)


def test_an_unsupported_timeframe_is_refused():
    result = connected_client().get_rates("EURUSD", "Z9", 5)
    assert not result.ok and result.code == "UNSUPPORTED_TIMEFRAME"


@pytest.mark.parametrize(("name", "code"), [
    ("M5", 5), ("M15", 15), ("M30", 30), ("H1", 16385), ("H4", 16388), ("D1", 16408),
])
def test_timeframe_codes_match_metatrader_constants(name, code):
    assert mt5_timeframe(name) == code


def test_timeframe_code_prefers_the_live_module_constant():
    assert mt5_timeframe("M15", module()) == 15


class SpreadCases:
    monitor = None


def test_spread_monitor_classifies_normal_elevated_and_extreme():
    monitor = SpreadMonitor(window=10, elevated_ratio=1.5, extreme_ratio=3.0)
    for _ in range(5):
        assert monitor.observe("EURUSD", 0.0001).state is SpreadState.NORMAL
    assert monitor.observe("EURUSD", 0.00018).state is SpreadState.ELEVATED
    assert monitor.observe("EURUSD", 0.0010).state is SpreadState.EXTREME


def test_extreme_spread_is_recorded_as_blocking_new_entries():
    monitor = SpreadMonitor(window=10, extreme_ratio=2.0)
    for _ in range(5):
        monitor.observe("EURUSD", 0.0001)
    reading = monitor.observe("EURUSD", 0.001)
    assert reading.state is SpreadState.EXTREME and reading.blocks_new_entry
    assert reading.ratio and reading.ratio > 2.0


def test_spread_percentage_is_relative_to_mid_price():
    reading = SpreadMonitor().observe("EURUSD", 0.00011, mid_price=1.1)
    assert reading.spread_percent == pytest.approx(0.0001)


def test_a_missing_spread_is_unknown_not_zero():
    reading = SpreadMonitor().observe("EURUSD", None)
    assert reading.state is SpreadState.UNKNOWN and reading.spread is None


def test_reader_drops_a_bar_whose_interval_has_not_elapsed():
    reader = MT5MarketDataReader()
    unclosed = [{"time": int((NOW - timedelta(minutes=5)).timestamp()), "open": 1.1, "high": 1.2,
                 "low": 1.0, "close": 1.15, "tick_volume": 5, "spread": 10, "real_volume": 0}]
    assert reader.normalize_rates(unclosed, symbol="EURUSD", timeframe="M15", as_of=NOW) == []
