"""D1 through M5 must all validate (Phase 12 section 5)."""
from datetime import timedelta

import pytest

from data_quality.validator import timeframe_delta
from observation.quality_gate import DataQualityGate, GateVerdict
from tests.phase12_helpers import NOW, TIMEFRAMES, client


@pytest.fixture(scope="module")
def batches():
    connected = client()
    return {name: connected.get_rates("EURUSD", name, 120).data for name in TIMEFRAMES}


def test_every_required_timeframe_returns_data(batches):
    for name in TIMEFRAMES:
        assert batches[name], name


def test_every_timeframe_exposes_the_latest_candle_and_ohlc(batches):
    for name, candles in batches.items():
        last = candles[-1]
        assert last["timestamp"] is not None, name
        assert last["open"] and last["high"] and last["low"] and last["close"], name


def test_every_timeframe_is_ordered_and_free_of_duplicates(batches):
    for name, candles in batches.items():
        stamps = [row["timestamp"] for row in candles]
        assert stamps == sorted(stamps), name
        assert len(set(stamps)) == len(stamps), name


def test_every_timestamp_is_timezone_aware_and_utc(batches):
    for name, candles in batches.items():
        for row in candles:
            assert row["timestamp"].tzinfo is not None, name
            assert row["timestamp"].utcoffset().total_seconds() == 0, name


def test_no_timeframe_contains_a_future_candle(batches):
    for name, candles in batches.items():
        delta = timeframe_delta(name)
        assert all(row["timestamp"] + delta <= NOW for row in candles), name


def test_candles_sit_on_timeframe_boundaries(batches):
    for name, candles in batches.items():
        step = int(timeframe_delta(name).total_seconds())
        assert all(int(row["timestamp"].timestamp()) % step == 0 for row in candles), name


def test_every_timeframe_passes_the_quality_gate(batches):
    results = DataQualityGate(minimum_candles=60).evaluate_all(batches, symbol="EURUSD", as_of=NOW)
    assert set(results) == set(TIMEFRAMES)
    for name, result in results.items():
        assert result.verdict is GateVerdict.PASS, f"{name}: {result.reasons}"


def test_data_freshness_grows_with_the_timeframe(batches):
    results = DataQualityGate(minimum_candles=60).evaluate_all(batches, symbol="EURUSD", as_of=NOW)
    assert results["D1"].age_seconds > results["M5"].age_seconds
