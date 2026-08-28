"""The gate that stops a signal being generated on bad data (Phase 12 section 6)."""
from datetime import timedelta

import pytest

from observation.quality_gate import (
    BROKEN_OHLC,
    DUPLICATE_CANDLE,
    DataQualityGate,
    FUTURE_TIMESTAMP,
    GateVerdict,
    INSUFFICIENT_HISTORY,
    NAIVE_TIMESTAMP,
    NON_POSITIVE_PRICE,
    NO_DATA,
    OUT_OF_ORDER,
    STALE_DATA,
)
from tests.phase12_helpers import NOW, series


def gate(**kwargs):
    kwargs.setdefault("minimum_candles", 60)
    return DataQualityGate(**kwargs)


def evaluate(candles, **kwargs):
    return gate(**kwargs).evaluate(candles, symbol="EURUSD", timeframe="M15", as_of=NOW)


def test_clean_data_passes():
    result = evaluate(series(60))
    assert result.verdict is GateVerdict.PASS and result.signal_allowed
    assert result.reasons == ()


def test_a_future_timestamp_fails():
    candles = series(60)
    candles.append({**candles[-1], "timestamp": NOW + timedelta(minutes=15)})
    result = evaluate(candles)
    assert result.verdict is GateVerdict.FAIL and FUTURE_TIMESTAMP in result.reasons


def test_a_candle_whose_interval_has_not_elapsed_fails():
    """A bar opened 5 minutes ago on M15 is not closed yet."""
    candles = series(60)
    candles.append({**candles[-1], "timestamp": NOW - timedelta(minutes=5)})
    assert evaluate(candles).verdict is GateVerdict.FAIL


def test_a_duplicate_candle_fails():
    candles = series(60)
    candles.append(dict(candles[-1]))
    result = evaluate(candles)
    assert result.verdict is GateVerdict.FAIL and DUPLICATE_CANDLE in result.reasons


def test_out_of_order_candles_fail():
    candles = series(60)
    candles[10], candles[20] = candles[20], candles[10]
    result = evaluate(candles)
    assert result.verdict is GateVerdict.FAIL and OUT_OF_ORDER in result.reasons


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_a_non_positive_price_fails(field):
    candles = series(60)
    candles[-1] = {**candles[-1], field: 0}
    result = evaluate(candles)
    assert result.verdict is GateVerdict.FAIL and NON_POSITIVE_PRICE in result.reasons


def test_a_negative_price_fails():
    candles = series(60)
    candles[-1] = {**candles[-1], "low": -1.0}
    assert evaluate(candles).verdict is GateVerdict.FAIL


def test_broken_ohlc_fails():
    candles = series(60)
    candles[-1] = {**candles[-1], "high": 1.0, "low": 1.5}
    result = evaluate(candles)
    assert result.verdict is GateVerdict.FAIL and BROKEN_OHLC in result.reasons


def test_insufficient_history_fails():
    result = evaluate(series(10))
    assert result.verdict is GateVerdict.FAIL and INSUFFICIENT_HISTORY in result.reasons


def test_stale_data_fails():
    old = series(60, now=NOW - timedelta(days=3))
    result = evaluate(old)
    assert result.verdict is GateVerdict.FAIL and STALE_DATA in result.reasons


def test_a_naive_timestamp_fails():
    candles = series(60)
    candles[-1] = {**candles[-1], "timestamp": candles[-1]["timestamp"].replace(tzinfo=None)}
    result = evaluate(candles)
    assert result.verdict is GateVerdict.FAIL and NAIVE_TIMESTAMP in result.reasons


def test_no_data_fails():
    result = evaluate([])
    assert result.verdict is GateVerdict.FAIL and NO_DATA in result.reasons


def test_a_missing_candle_is_a_warning_not_a_failure():
    """Real feeds have weekend and holiday gaps; a gap must not stop analysis."""
    candles = series(70)
    del candles[30]
    result = evaluate(candles)
    assert result.verdict is GateVerdict.WARN and result.signal_allowed


def test_signal_allowed_requires_every_timeframe_to_pass():
    good = {"M15": series(60), "H1": series(60, timeframe="H1", step_minutes=60)}
    results = gate().evaluate_all(good, symbol="EURUSD", as_of=NOW)
    assert DataQualityGate.signal_allowed(results)

    bad = {**good, "M5": series(3, timeframe="M5", step_minutes=5)}
    results = gate().evaluate_all(bad, symbol="EURUSD", as_of=NOW)
    assert not DataQualityGate.signal_allowed(results)


def test_an_empty_result_set_is_not_allowed():
    assert not DataQualityGate.signal_allowed({})
