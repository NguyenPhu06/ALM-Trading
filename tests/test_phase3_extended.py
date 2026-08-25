from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ai.datasets import DatasetRow
from ai.features import StableFeatureSchema
from ai.labels import ForwardLabeler
from backtest import DCAConfig, DCASimulator, EvaluationAction, TimeBasedExitEngine, TradeDirection
from data_sources.market_data import MockProvider
from data_sources.snapshot_pipeline import HistoricalFeaturePipeline
from database.repositories import SimulatedTradeRepository
from features.candles import candle_close_time
from features.intelligence import MarketIntelligenceEngine, MarketIntelligenceService, TimeframeIntelligence
from features.liquidity import LiquidityEngine
from features.store import FeatureStore
from tests.fixtures import deterministic_m15_candles


UTC = timezone.utc
BASE = datetime(2026, 8, 20, tzinfo=UTC)


def state(timeframe, trend, *, available=True, choch=None):
    return TimeframeIntelligence(
        BASE, "EURUSD", timeframe, available, trend, "HH" if trend == "BULLISH" else "LL" if trend == "BEARISH" else None,
        trend if trend in {"BULLISH", "BEARISH"} else None, choch, 1.2, 1.0,
        {"nearest_buy_side": 1.2, "nearest_sell_side": 1.0, "level_count": 2, "levels": []},
        None, None, None, None,
        {"rsi": 55.0, "adx": 30.0, "atr": 0.001, "trend_direction": trend, "close": 1.1, "spread": 0.0001},
        {"state": "NORMAL_VOLATILITY"}, "LONDON", 0.01,
        ohlcv={"open": 1.1, "high": 1.2, "low": 1.0, "close": 1.1, "volume": 10.0},
        candle_closed=True, internal_structure="HL", swing_structure="HH",
        premium_discount="EQUILIBRIUM", regime="TRANSITIONAL" if choch else trend,
    )


def test_mtf_regime_preserves_bullish_htf_and_bearish_ltf():
    engine = MarketIntelligenceEngine()
    states = {timeframe: state(timeframe, "RANGING") for timeframe in engine.TIMEFRAMES}
    for timeframe in ("D1", "H4", "H1"):
        states[timeframe] = state(timeframe, "BULLISH")
    for timeframe in ("M30", "M15", "M5"):
        states[timeframe] = state(timeframe, "BEARISH")
    snapshot = engine.aggregate("EURUSD", states, as_of=BASE)
    assert snapshot.market_regime == {
        "state": "TRANSITIONAL", "higher_timeframe_bias": "BULLISH",
        "lower_timeframe_state": "BEARISH", "alignment": "COUNTER_TREND",
        "confidence": 92.0,
    }


def test_timeframe_snapshot_contains_ohlcv_structure_premium_and_quality():
    rows = deterministic_m15_candles(80)
    snapshot = MarketIntelligenceEngine().calculate("EURUSD", {"M15": rows}, as_of=candle_close_time(rows[-1]))
    m15 = snapshot.timeframes["M15"]
    assert set(m15.ohlcv) == {"open", "high", "low", "close", "volume"}
    assert m15.candle_closed is True
    assert m15.internal_structure is not None and m15.swing_structure is not None
    assert m15.premium_discount in {"PREMIUM", "DISCOUNT", "EQUILIBRIUM"}
    assert "M30" in snapshot.data_quality["missing_timeframes"]
    assert snapshot.data_quality["all_candles_closed"] is True


def test_liquidity_map_tracks_swept_and_swept_at():
    rows = [
        {"timestamp": BASE + timedelta(minutes=15 * index), "symbol": "EURUSD", "timeframe": "M15",
         "open": Decimal(str(values[0])), "high": Decimal(str(values[1])), "low": Decimal(str(values[2])),
         "close": Decimal(str(values[3])), "volume": Decimal("1"), "is_closed": True}
        for index, values in enumerate([(10, 11, 9, 10), (10, 12, 10, 11), (11, 11.5, 9, 10), (11.7, 12.2, 11, 11.8)])
    ]
    entries = LiquidityEngine(swing_left_bars=1, swing_right_bars=1).liquidity_map(rows)
    swept = next(entry for entry in entries if entry.type == "CONFIRMED_SWING_HIGH")
    assert swept.swept is True and swept.swept_at is not None
    assert swept.created_at < swept.swept_at


def test_feature_store_is_per_candle_and_future_safe():
    rows = deterministic_m15_candles(10)
    for index, row in enumerate(rows):
        row["timeframe"] = "M5"
        row["timestamp"] = BASE + timedelta(minutes=5 * index)
    store = FeatureStore()
    prefix = store.generate("EURUSD", {"M5": rows[:5]})
    extended = store.generate("EURUSD", {"M5": rows})
    assert len(extended) == 10
    assert [record.features for record in prefix] == [record.features for record in extended[:5]]
    names = set(extended[-1].features.names)
    assert {"trend_m30", "premium_discount", "ichimoku_state", "spread", "news_risk"} <= names


def test_mock_provider_and_historical_feature_pipeline_are_idempotent(db_session):
    rows = deterministic_m15_candles(20)
    provider = MockProvider(rows)
    pipeline = HistoricalFeaturePipeline(db_session, provider)
    first = pipeline.run("EURUSD", timeframes=("M15",))
    second = pipeline.run("EURUSD", timeframes=("M15",))
    assert first.rows_received == 20 and first.rows_inserted == 20
    assert second.rows_inserted == 0 and second.rows_skipped == 20
    assert first.snapshot.timeframes["M15"].available is True


def test_pipeline_rejects_provider_timeframe_mismatch_before_writes(db_session):
    class BadProvider(MockProvider):
        def get_candles(self, symbol, timeframe, *, limit=None):
            rows = deterministic_m15_candles(2)
            rows[0]["timeframe"] = "H1"
            return rows

    with pytest.raises(ValueError, match="mismatched"):
        HistoricalFeaturePipeline(db_session, BadProvider([])).run("EURUSD", timeframes=("M15",))


def test_dca_simulation_limits_countertrend_and_trade_audit(db_session):
    simulator = DCASimulator(DCAConfig(
        maximum_entries=2, maximum_exposure=2.0, distance_between_entries=0.01,
        maximum_drawdown=0.20, time_based_exit=timedelta(hours=4),
    ))
    position = simulator.open(
        timestamp=BASE, price=1.10, direction=TradeDirection.LONG, size=1.0,
        higher_timeframe_bias="BEARISH", reason="SIMULATION_ONLY",
    )
    assert position.counter_trend_trade is True
    assert simulator.consider_entry(position, timestamp=BASE + timedelta(hours=1), price=1.08, size=1.0, reason="DISTANCE_MET")
    assert not simulator.consider_entry(position, timestamp=BASE + timedelta(hours=2), price=1.06, size=1.0, reason="MAX_ENTRIES")
    trade = simulator.close(position, timestamp=BASE + timedelta(hours=3), price=1.12, reason="TEST_EXIT")
    stored = SimulatedTradeRepository(db_session).add(trade)
    assert stored.counter_trend_trade is True
    assert stored.entry_time.replace(tzinfo=UTC) == trade.entry_time
    assert stored.exit_time.replace(tzinfo=UTC) == trade.exit_time
    assert stored.direction == "LONG" and stored.size == 2.0


def test_time_based_exit_returns_hold_exit_reduce_and_invalidate():
    engine = MarketIntelligenceEngine()
    states = {timeframe: state(timeframe, "BULLISH") for timeframe in engine.TIMEFRAMES}
    snapshot = engine.aggregate("EURUSD", states, as_of=BASE)
    position = DCASimulator().open(
        timestamp=BASE, price=1.10, direction=TradeDirection.LONG, size=1.0,
        higher_timeframe_bias="BULLISH", reason="TEST",
    )
    evaluator = TimeBasedExitEngine(maximum_holding_time=timedelta(hours=2), reduce_drawdown=0.01)
    assert evaluator.evaluate(position, snapshot, timestamp=BASE + timedelta(hours=1), current_price=1.11).action is EvaluationAction.HOLD
    assert evaluator.evaluate(position, snapshot, timestamp=BASE + timedelta(hours=3), current_price=1.11).action is EvaluationAction.EXIT
    assert evaluator.evaluate(position, snapshot, timestamp=BASE + timedelta(hours=1), current_price=1.08).action is EvaluationAction.REDUCE
    invalid = replace(snapshot, market_regime={**snapshot.market_regime, "higher_timeframe_bias": "BEARISH"})
    assert evaluator.evaluate(position, invalid, timestamp=BASE + timedelta(hours=1), current_price=1.10).action is EvaluationAction.INVALIDATE


def test_forward_labels_use_future_only_in_label_and_align_with_features():
    rows = [
        {"timestamp": BASE + timedelta(minutes=5 * index), "symbol": "EURUSD", "timeframe": "M5",
         "open": Decimal(str(price)), "high": Decimal(str(price + 1)), "low": Decimal(str(price - 1)),
         "close": Decimal(str(price)), "volume": Decimal("1"), "is_closed": True}
        for index, price in enumerate((100, 101, 102, 99))
    ]
    labels = ForwardLabeler(horizon_bars=2).generate(rows)
    assert labels[0].future_return == pytest.approx(0.02)
    assert labels[0].maximum_favorable_excursion == pytest.approx(0.03)
    assert labels[0].label_end_timestamp > labels[0].timestamp

    snapshot = MarketIntelligenceEngine().calculate("EURUSD", {"M5": rows[:1]}, as_of=candle_close_time(rows[0]))
    features = StableFeatureSchema.extract(snapshot)
    row = DatasetRow(snapshot.timestamp, "EURUSD", snapshot.calculation_version, features, labels[0])
    assert row.label.label_end_timestamp > row.feature_timestamp
    serialized = json.dumps(MarketIntelligenceService._jsonable(snapshot))
    assert '"signal": null' in serialized
