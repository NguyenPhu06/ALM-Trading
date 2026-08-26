"""Integration against a real MetaTrader 5 terminal, plus a full mock pipeline run.

The live tests skip cleanly when the MetaTrader5 package or a running terminal is
absent, which is the normal case on Linux/Docker and on any machine without the
terminal installed. They never send an order.
"""
import pytest

from data_sources.providers.mt5 import MT5MarketDataProvider
from database.models import (
    MT5AccountSnapshotRecord,
    MT5DataQualityEventRecord,
    MT5PositionSnapshotRecord,
    MT5TickSnapshotRecord,
)
from execution.mt5.account import TradeMode
from execution.mt5.client import MT5ReadOnlyClient
from execution.mt5.connection import ConnectionState, load_mt5_module
from execution.mt5.service import MT5ReadOnlyService
from tests.phase10_helpers import EXTERNAL_POSITION, TIMEFRAMES, connected_client, positions

live = pytest.mark.skipif(
    load_mt5_module() is None,
    reason="MetaTrader5 package or terminal unavailable on this host",
)


# ------------------------------------------------------- full pipeline (mock)
def test_the_whole_read_only_pipeline_runs_against_a_mock_terminal(db_session):
    client = connected_client(positions=positions(EXTERNAL_POSITION))
    service = MT5ReadOnlyService(db_session, client=client)

    assert service.connect().state is ConnectionState.CONNECTED
    assert service.sync_symbols().ok
    assert service.sync_tick("EURUSD").ok
    assert service.sync_positions().ok
    outcome = service.sync_market_data("EURUSD", count=60)

    assert set(outcome.timeframes) == set(TIMEFRAMES)
    assert all(count > 0 for count in outcome.timeframes.values())
    assert set(outcome.quality.values()) == {"VALID"}

    assert db_session.query(MT5AccountSnapshotRecord).count() == 1
    assert db_session.query(MT5TickSnapshotRecord).count() == 1
    assert db_session.query(MT5PositionSnapshotRecord).count() == 1
    assert db_session.query(MT5DataQualityEventRecord).count() == len(TIMEFRAMES)

    status = service.status()
    assert status["environment"] == "DEMO" and status["connection"] == "ONLINE"
    assert status["read_only"] is True and status["execution_enabled"] is False


def test_mt5_candles_feed_the_existing_market_data_pipeline(db_session):
    """MT5 must reach the feature stack through the ordinary provider contract."""
    from data_sources.ingestion import MarketDataIngestionService

    provider = MT5MarketDataProvider(connected_client(), symbols=("EURUSD",))
    provider.connect()
    candles = provider.get_candles("EURUSD", "M15", limit=50)
    assert candles
    report = MarketDataIngestionService(db_session, provider).import_historical(
        "EURUSD", "M15", candles[0]["timestamp"], candles[-1]["timestamp"])
    assert report.rows_inserted > 0

    from database.repositories import CandleRepository

    stored = CandleRepository(db_session).recent_chronological(
        symbol="EURUSD", timeframe="M15", closed_only=True, limit=50)
    assert stored and all(row.source == "mt5" for row in stored)


def test_paper_trading_is_unaffected_by_the_mt5_integration():
    """MT5 is a data provider; the paper engine keeps its own simulated book."""
    from paper import PaperTradingService
    from tests.phase8_helpers import PRED, QUOTE, RISK_OK, request

    service = PaperTradingService()
    service.start()
    result = service.enter(request(), quote=QUOTE, setup_status="EXECUTABLE_SIMULATION",
                           risk_decision=RISK_OK, data_quality="VALID",
                           provider_status="ONLINE", prediction=PRED)
    assert result.accepted and len(service.positions) == 1
    assert not hasattr(service, "mt5") and not hasattr(service, "broker")


# ------------------------------------------------------------- live terminal
@live
def test_live_terminal_connects_to_a_demo_account_and_reads_every_timeframe():
    client = MT5ReadOnlyClient()
    report = client.connect()
    if report.state is not ConnectionState.CONNECTED:
        pytest.skip(f"terminal not connected: {report.code}")
    try:
        account = client.get_account()
        assert account.ok, account.code
        assert account.data.trade_mode is not TradeMode.REAL, "REAL account must never be used"
        assert account.data.environment == "DEMO"
        assert account.data.server

        symbols = client.get_symbols()
        assert symbols.ok and symbols.data

        resolved = client.resolve_symbol("EURUSD")
        if not resolved.ok:
            pytest.skip(f"EURUSD unavailable on this broker: {resolved.code}")

        tick = client.get_tick("EURUSD")
        assert tick.ok and tick.data["bid"] and tick.data["ask"]

        for timeframe in TIMEFRAMES:
            rates = client.get_rates("EURUSD", timeframe, 50)
            assert rates.ok, f"{timeframe}: {rates.code}"
            assert rates.data, timeframe

        assert client.get_positions().ok
        assert client.get_orders().ok
        assert str(client.health_check().state) in {"ONLINE", "DEGRADED", "STALE"}
    finally:
        client.disconnect()


@live
def test_live_terminal_never_exposes_an_execution_method():
    client = MT5ReadOnlyClient()
    for name in ("send_order", "close_position", "modify_order", "open_position", "place_dca"):
        assert not hasattr(client, name)
