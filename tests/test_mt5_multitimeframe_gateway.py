"""The MTF ladder reaches the gateway and the dashboard, not just the client."""
from execution.mt5.service import MT5ReadOnlyService
from data_sources.providers.mt5 import MT5MarketDataProvider
from tests.phase10_helpers import TIMEFRAMES, connected_client


def test_the_client_serves_the_whole_ladder_in_one_call():
    results = connected_client().get_multi_timeframe_rates("EURUSD", count=40)
    assert tuple(results) == TIMEFRAMES
    assert all(result.ok and result.data for result in results.values())


def test_the_service_reports_every_timeframe_with_age_and_source(db_session):
    service = MT5ReadOnlyService(db_session, client=connected_client())
    payload = service.multi_timeframe("EURUSD", count=40)
    assert tuple(payload) == TIMEFRAMES
    for timeframe, entry in payload.items():
        assert entry["available"], timeframe
        assert entry["source"] == "mt5"
        assert entry["data_age_seconds"] >= 0
        assert entry["last_candle"] is not None


def test_older_timeframes_report_a_larger_data_age(db_session):
    service = MT5ReadOnlyService(db_session, client=connected_client())
    payload = service.multi_timeframe("EURUSD", count=40)
    assert payload["D1"]["data_age_seconds"] > payload["M5"]["data_age_seconds"]


def test_the_provider_bridges_every_timeframe_into_the_alm_pipeline():
    provider = MT5MarketDataProvider(connected_client(), symbols=("EURUSD",))
    for timeframe in TIMEFRAMES:
        candles = provider.get_candles("EURUSD", timeframe, limit=20)
        assert candles, timeframe
        assert candles[-1]["source"] == "mt5" and candles[-1]["symbol"] == "EURUSD"
