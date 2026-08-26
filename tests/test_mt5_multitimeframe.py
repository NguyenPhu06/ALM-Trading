"""D1 through M5 must all be available, not only M15."""
import pytest

from tests.phase10_helpers import NOW, TIMEFRAMES, connected_client

pytestmark = pytest.mark.parametrize("timeframe", TIMEFRAMES)


def test_every_required_timeframe_returns_candles(timeframe):
    result = connected_client().get_rates("EURUSD", timeframe, 50)
    assert result.ok, f"{timeframe}: {result.code}"
    assert len(result.data) > 0
    assert result.data[-1]["timeframe"] == timeframe


def test_every_timeframe_is_closed_and_not_in_the_future(timeframe):
    candles = connected_client().get_rates("EURUSD", timeframe, 30).data
    assert all(candle["is_closed"] for candle in candles)
    assert all(candle["timestamp"] <= NOW for candle in candles)
