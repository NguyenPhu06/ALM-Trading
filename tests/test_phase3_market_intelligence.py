from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from database.models import MarketIntelligenceSnapshot
from database.repositories import CandleRepository, MarketIntelligenceRepository
from features.indicators import MTFIndicatorEngine
from features.intelligence import MarketBias, MarketIntelligenceEngine, MarketIntelligenceService, TimeframeIntelligence
from features.liquidity import LiquidityEngine
from features.session import SessionEngine
from features.smc import DisplacementDetector, FairValueGapDetector, OrderBlockDetector, RejectionDetector
from features.structure import SwingDetector
from features.volatility import VolatilityEngine
from tests.fixtures import deterministic_m15_candles


UTC = timezone.utc
BASE = datetime(2026, 8, 20, tzinfo=UTC)


def candles(rows, *, timeframe="M15", start=BASE):
    minutes = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}[timeframe]
    return [{
        "timestamp": start + timedelta(minutes=minutes * index), "symbol": "EURUSD", "timeframe": timeframe,
        "open": Decimal(str(row[0])), "high": Decimal(str(row[1])), "low": Decimal(str(row[2])),
        "close": Decimal(str(row[3])), "volume": Decimal(str(row[4] if len(row) > 4 else 100)),
        "is_closed": True, "source": "phase3_fixture", "provider": "phase3_fixture",
    } for index, row in enumerate(rows)]


def test_swing_detector_exposes_unconfirmed_without_using_it_as_confirmed():
    rows = candles([(10, 11, 9, 10), (10, 13, 10, 12)])
    detector = SwingDetector(1, 1, minimum_distance=1, minimum_price_move="0.1")
    assert detector.detect(rows) == []
    candidates = detector.detect(rows, include_unconfirmed=True)
    assert candidates and candidates[-1].confirmed is False
    assert candidates[-1].confirmation_timestamp is None


def test_liquidity_pool_is_created_from_equal_highs_and_labeled_buy_side():
    rows = candles([
        (10, 10.5, 9.5, 10), (10, 12, 10, 11), (10, 11, 8, 9),
        (9, 12.00002, 10, 11), (10, 11, 8.5, 9), (9, 10, 9, 9.5),
    ])
    levels = LiquidityEngine(
        swing_left_bars=1, swing_right_bars=1,
        equal_level_tolerance_points=3, point_size="0.00001",
    ).levels(rows)
    pool = next(level for level in levels if level.level_type == "BUY_SIDE_LIQUIDITY_POOL")
    assert pool.touches == 2 and pool.equal_level is True


def test_fvg_open_partial_and_future_safe():
    rows = candles([
        (10, 11, 9, 10), (10, 12, 10, 11), (13, 14, 12, 13.5),
        (13, 13.5, 11.5, 12.5),
    ])
    detector = FairValueGapDetector(minimum_size="0.5")
    open_gap = detector.detect(rows, as_of_index=2)[0]
    partial = detector.detect(rows)[0]
    assert open_gap.direction == "BULLISH" and open_gap.state == "OPEN"
    assert partial.state == "PARTIALLY_FILLED" and partial.fill_percentage == 50.0
    assert open_gap.timestamp == partial.timestamp


def test_displacement_order_block_and_rejection_are_deterministic():
    rows = candles([(1.00, 1.01, 0.99, 1.001)] * 14 + [
        (1.001, 1.01, 0.99, 0.995),
        (0.995, 1.08, 0.994, 1.075, 500),
    ])
    displacement = DisplacementDetector(atr_period=5, minimum_atr_ratio=1.5).detect(rows)[-1]
    assert displacement.displaced and displacement.direction == "BULLISH"
    blocks = OrderBlockDetector(lookback=5, atr_period=5, minimum_atr_ratio=1.5).detect(rows)
    assert blocks and blocks[-1].direction == "BULLISH"
    rejection = RejectionDetector(minimum_wick_ratio=0.5).detect(candles([(1, 1.2, 0.5, 1.1)]))[0]
    assert rejection.rejected and rejection.direction == "BULLISH"


def test_extended_indicators_and_volatility_are_causal():
    rows = deterministic_m15_candles(100)
    engine = MTFIndicatorEngine()
    at_90 = rows[89]["timestamp"] + timedelta(minutes=15)
    prefix = engine.calculate(rows[:90], "M15", as_of=at_90)
    extended = engine.calculate(rows, "M15", as_of=at_90)
    assert prefix == extended
    assert prefix.available and prefix.rsi is not None and prefix.adx is not None
    assert prefix.plus_di is not None and prefix.minus_di is not None
    assert prefix.atr_percentage is not None and prefix.volatility_state is not None
    assert prefix.ichimoku_chikou == float(rows[89]["close"])
    volatility = VolatilityEngine().calculate(rows[:90])
    assert volatility and volatility.calculation_version == "phase3.v1"


def test_session_statistics_are_running_not_future_final():
    rows = candles([(10, 11, 9, 10), (10, 13, 8, 12), (12, 14, 7, 13)], timeframe="H1")
    stats = SessionEngine().statistics(rows)
    assert stats[0].high == 11 and stats[0].low == 9
    assert stats[1].high == 13 and stats[1].low == 8
    assert stats[0].calculation_version == "phase3.v1"


def state(timeframe, trend="UNKNOWN", *, bos=None, sweep=None, displacement=None, available=True):
    return TimeframeIntelligence(
        BASE, "EURUSD", timeframe, available, trend, None, bos, None, None, None,
        {"nearest_buy_side": 1.2, "nearest_sell_side": 1.0, "level_count": 2},
        sweep, None, None, displacement,
        {"rsi": 55.0, "adx": 30.0, "atr": 0.001, "trend_strength": "MODERATE_TREND", "close": 1.1, "spread": None},
        {"state": "NORMAL_VOLATILITY"}, "LONDON", 0.01,
    )


def test_deterministic_mtf_market_intelligence_scenario():
    engine = MarketIntelligenceEngine()
    states = {
        "D1": state("D1", "BULLISH", bos="BULLISH"),
        "H4": state("H4", "BULLISH", bos="BULLISH"),
        "H1": state("H1", "BULLISH", bos="BULLISH"),
        "M30": state("M30", "BEARISH"),
        "M15": state("M15", "BEARISH"),
        "M5": state("M5", sweep={"direction": "BULLISH", "metadata": {"liquidity_side": "SELL_SIDE"}}),
        "M1": state("M1", displacement={"direction": "BULLISH", "displaced": True}),
    }
    snapshot = engine.aggregate("EURUSD", states, as_of=BASE)
    assert snapshot.bias in {MarketBias.BULLISH, MarketBias.STRONG_BULLISH}
    assert snapshot.timeframes["M30"].trend == "BEARISH"
    assert snapshot.timeframes["M15"].trend == "BEARISH"
    assert snapshot.timeframes["M5"].sweep["metadata"]["liquidity_side"] == "SELL_SIDE"
    assert snapshot.timeframes["M1"].displacement["direction"] == "BULLISH"
    assert any("M15 bearish" in conflict for conflict in snapshot.conflicts)
    assert snapshot.trade_state == "OBSERVE" and snapshot.signal is None
    assert snapshot.market_regime["higher_timeframe_bias"] == "BULLISH"
    assert snapshot.market_regime["lower_timeframe_state"] == "BEARISH"
    assert snapshot.mtf_alignment == "COUNTER_TREND"
    assert snapshot.confidence > 0


def test_no_trade_for_conflicting_htf_and_feature_vector_schema_is_stable():
    engine = MarketIntelligenceEngine()
    states = {timeframe: state(timeframe, available=False) for timeframe in engine.TIMEFRAMES}
    states["D1"] = state("D1", "BULLISH", bos="BULLISH")
    states["H4"] = state("H4", "BEARISH", bos="BEARISH")
    states["H1"] = state("H1", "RANGING")
    snapshot = engine.aggregate("EURUSD", states, as_of=BASE)
    assert snapshot.trade_state == "NO_TRADE"
    assert "CONFLICTING_HIGHER_TIMEFRAMES" in snapshot.no_trade_reasons
    assert {"trend_d1", "rsi_h1", "atr_m15", "liquidity_distance", "sweep_direction", "session", "volatility_state"} <= set(snapshot.feature_vector.names)
    assert len(snapshot.feature_vector.names) == len(snapshot.feature_vector.values)


def test_future_candle_cannot_change_any_market_intelligence_feature():
    rows = deterministic_m15_candles(90)
    cutoff = rows[79]["timestamp"] + timedelta(minutes=15)
    engine = MarketIntelligenceEngine()
    before = engine.calculate("EURUSD", {"M15": rows[:80]}, as_of=cutoff)
    after = engine.calculate("EURUSD", {"M15": rows}, as_of=cutoff)
    assert before.timeframes["M15"] == after.timeframes["M15"]
    assert before.bias == after.bias
    assert before.confluence == after.confluence
    assert before.feature_vector == after.feature_vector


def test_snapshot_database_upsert_and_query(db_session):
    for row in deterministic_m15_candles(80):
        CandleRepository(db_session).add(row)
    service = MarketIntelligenceService(db_session)
    snapshot = service.calculate("EURUSD")
    first = service.persist(snapshot)
    second = service.persist(snapshot)
    assert first == second
    rows = MarketIntelligenceRepository(db_session).list(symbol="EURUSD", timeframe="MTF")
    assert len(rows) == 1 and rows[0].calculation_version == "phase3.v1"
    assert db_session.query(MarketIntelligenceSnapshot).count() == first
    m15 = MarketIntelligenceRepository(db_session).list(symbol="EURUSD", timeframe="M15")[0]
    assert m15.market_candle_id is not None


def test_market_intelligence_does_not_use_sample_csv_by_default(db_session):
    for row in deterministic_m15_candles(80):
        row["source"] = "local_csv"
        CandleRepository(db_session).add(row)
    snapshot = MarketIntelligenceService(db_session).calculate("EURUSD")
    assert snapshot.timeframes["M15"].available is False
    assert snapshot.trade_state == "NO_TRADE"


def test_phase3_intelligence_apis(client, db_session):
    for row in deterministic_m15_candles(80):
        CandleRepository(db_session).add(row)
    for path in (
        "/api/intelligence/EURUSD", "/api/intelligence/EURUSD/mtf",
        "/api/intelligence/EURUSD/M15", "/api/liquidity/EURUSD",
        "/api/structure/EURUSD", "/api/indicators/EURUSD/M15",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        assert "secret" not in response.text.lower()
    payload = client.get("/api/intelligence/EURUSD").json()
    assert payload["signal"] is None
    assert payload["calculation_version"] == "phase3.v1"
    assert payload["timeframes"]["M15"]["available"] is True
    assert client.get("/api/intelligence/EURUSD/M30").status_code == 200
    assert client.get("/api/intelligence/EURUSD/M2").status_code == 422
