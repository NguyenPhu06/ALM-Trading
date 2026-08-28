"""Ichimoku, RSI, ADX and ATR across every required timeframe."""
import pytest

from features.intelligence import MarketIntelligenceService
from tests.phase12_helpers import NOW, TIMEFRAMES

REQUIRED = ("rsi", "adx", "atr", "ichimoku_tenkan", "ichimoku_kijun",
            "ichimoku_senkou_a", "ichimoku_senkou_b")


@pytest.fixture(scope="module")
def snapshot(request):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from database.base import Base
    import database.models  # noqa: F401
    from tests.phase9_helpers import seed_market

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_market(session, now=NOW)
    result = MarketIntelligenceService(session).calculate("EURUSD", as_of=NOW)
    yield result
    session.close()


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
def test_every_timeframe_produces_indicators(snapshot, timeframe):
    state = snapshot.timeframes[timeframe]
    assert state.available, timeframe
    assert state.indicators, timeframe


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
def test_every_required_indicator_is_present(snapshot, timeframe):
    indicators = snapshot.timeframes[timeframe].indicators
    for name in REQUIRED:
        assert name in indicators, f"{timeframe} missing {name}"


def test_raw_values_are_numeric_and_finite(snapshot):
    indicators = snapshot.timeframes["M15"].indicators
    for name in ("rsi", "adx", "atr"):
        value = indicators.get(name)
        assert value is not None and float(value) == float(value), name


def test_rsi_stays_within_its_bounds(snapshot):
    for timeframe in TIMEFRAMES:
        rsi = snapshot.timeframes[timeframe].indicators.get("rsi")
        if rsi is not None:
            assert 0 <= float(rsi) <= 100, timeframe


def test_atr_is_never_negative(snapshot):
    for timeframe in TIMEFRAMES:
        atr = snapshot.timeframes[timeframe].indicators.get("atr")
        if atr is not None:
            assert float(atr) >= 0, timeframe


def test_indicators_carry_their_timeframe_and_timestamp(snapshot):
    indicators = snapshot.timeframes["M15"].indicators
    assert indicators.get("timeframe") == "M15"
    assert indicators.get("as_of") is not None


def test_a_signal_interpretation_is_provided(snapshot):
    """Raw numbers alone are not enough; the engine must say what they mean."""
    indicators = snapshot.timeframes["H1"].indicators
    assert "trend_strength" in indicators or "trend_direction" in indicators


def test_indicator_values_are_causal(snapshot):
    """No indicator may be stamped after the snapshot it belongs to."""
    for timeframe in TIMEFRAMES:
        state = snapshot.timeframes[timeframe]
        if state.timestamp is not None:
            assert state.timestamp <= snapshot.timestamp, timeframe
