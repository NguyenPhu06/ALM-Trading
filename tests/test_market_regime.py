from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from database.repositories import CandleRepository
from features.indicators import IndicatorSnapshot, MTFIndicatorEngine
from features.liquidity import LiquidityEventData
from features.regime import (
    AlignmentLevel,
    InstitutionalFlowInput,
    MarketRegimeEngine,
    MarketState,
    ReversalConfidence,
    StructuralTrend,
)
from features.structure import StructureEventData
from features.liquidity import LiquidityEngine
from strategy.regime_input import RegimeDrivenStrategy
import inspect
from tests.fixtures import deterministic_m15_candles


NOW = datetime(2026, 8, 22, tzinfo=timezone.utc)
TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")


def structure_sequence(timeframe: str, direction: str, *, at: datetime = NOW, choch: bool = False):
    if direction == "BULLISH":
        kinds = ("HH", "HL", "BULLISH_BOS")
        price = Decimal("1.2")
    else:
        kinds = ("LH", "LL", "BEARISH_BOS")
        price = Decimal("1.0")
    events = [StructureEventData(at, "EURUSD", timeframe, kind, direction, price, at, 70.0) for kind in kinds]
    if choch:
        events.append(StructureEventData(at, "EURUSD", timeframe, f"{direction}_CHOCH", direction, price, at, 70.0))
    return events


def empty_indicators():
    return {
        timeframe: IndicatorSnapshot(timeframe, NOW, False, None, None, None, None, None, None, None, "TEST_UNAVAILABLE")
        for timeframe in TIMEFRAMES
    }


def calculate(structure, *, liquidity=None, available=TIMEFRAMES, indicators=None, institutional=None):
    return MarketRegimeEngine().calculate(
        symbol="EURUSD", as_of=NOW, available_timeframes=available,
        structure_events=structure,
        liquidity_events=liquidity or {}, indicators=indicators or empty_indicators(),
        current_price=Decimal("1.1"), institutional=institutional,
    )


@pytest.mark.parametrize("timeframe", TIMEFRAMES)
@pytest.mark.parametrize(
    ("direction", "expected"),
    [("BULLISH", StructuralTrend.BULLISH), ("BEARISH", StructuralTrend.BEARISH)],
)
def test_each_timeframe_has_independent_structural_trend(timeframe, direction, expected):
    snapshot = calculate({timeframe: structure_sequence(timeframe, direction)}, available=(timeframe,))
    state = snapshot.trend_matrix.timeframes[timeframe]
    assert state.trend is expected
    assert state.structure_state == f"{direction}_SEQUENCE"
    assert state.hh + state.hl + state.lh + state.ll == 2


def test_single_candle_or_single_event_cannot_define_trend():
    one_event = StructureEventData(NOW, "EURUSD", "H4", "HH", "BULLISH", Decimal("1.2"), NOW)
    state = calculate({"H4": [one_event]}, available=("H4",)).trend_matrix.timeframes["H4"]
    assert state.trend is StructuralTrend.NEUTRAL
    assert state.structure_state == "INSUFFICIENT_STRUCTURAL_SEQUENCE"


def test_m15_cannot_override_bearish_d1_h4_h1_and_is_retracement():
    structure = {
        "D1": structure_sequence("D1", "BEARISH"),
        "H4": structure_sequence("H4", "BEARISH"),
        "H1": structure_sequence("H1", "BEARISH"),
        "M15": structure_sequence("M15", "BULLISH"),
        "M5": structure_sequence("M5", "BULLISH"),
        "M1": structure_sequence("M1", "BULLISH"),
    }
    snapshot = calculate(structure)
    assert snapshot.htf_bias in {StructuralTrend.BEARISH, StructuralTrend.STRONGLY_BEARISH}
    assert snapshot.ltf_direction in {StructuralTrend.BULLISH, StructuralTrend.STRONGLY_BULLISH}
    assert snapshot.market_state is MarketState.TREND_RETRACEMENT
    assert snapshot.htf_structure_score < 0
    assert snapshot.timeframe_alignment is AlignmentLevel.LOW
    assert snapshot.signal is None


def test_possible_and_confirmed_reversal_require_h1_then_h4():
    possible = calculate({
        "D1": structure_sequence("D1", "BEARISH"),
        "H4": structure_sequence("H4", "BEARISH"),
        "H1": structure_sequence("H1", "BULLISH"),
        "M15": structure_sequence("M15", "BULLISH"),
    })
    confirmed = calculate({
        "D1": structure_sequence("D1", "BEARISH"),
        "H4": structure_sequence("H4", "BULLISH"),
        "H1": structure_sequence("H1", "BULLISH"),
        "M15": structure_sequence("M15", "BULLISH"),
    })
    assert possible.market_state is MarketState.POSSIBLE_REVERSAL
    assert confirmed.market_state is MarketState.CONFIRMED_REVERSAL


def test_m15_choch_and_sweep_alone_keep_reversal_confidence_low():
    structure = {
        "D1": structure_sequence("D1", "BEARISH"),
        "H4": structure_sequence("H4", "BEARISH"),
        "H1": structure_sequence("H1", "BEARISH"),
        "M15": structure_sequence("M15", "BULLISH", choch=True),
    }
    sweep = LiquidityEventData(
        NOW, "EURUSD", "M15", "LIQUIDITY_SWEEP", "BULLISH", Decimal("1.1"), NOW, 75.0,
        {"level_type": "CONFIRMED_SWING_LOW", "liquidity_level": "1.0"},
    )
    snapshot = calculate(structure, liquidity={"M15": [sweep]})
    assert snapshot.reversal_confidence is ReversalConfidence.LOW
    assert snapshot.market_state is MarketState.TREND_RETRACEMENT


def test_reversal_confidence_increases_only_with_h1_and_h4_confirmation():
    sweep = LiquidityEventData(
        NOW, "EURUSD", "M15", "LIQUIDITY_SWEEP", "BULLISH", Decimal("1.1"), NOW, 75.0,
        {"level_type": "CONFIRMED_SWING_LOW", "liquidity_level": "1.0"},
    )
    medium_structure = {
        "D1": structure_sequence("D1", "BEARISH"),
        "H4": structure_sequence("H4", "BEARISH"),
        "H1": structure_sequence("H1", "BULLISH"),
        "M15": structure_sequence("M15", "BULLISH", choch=True),
    }
    high_structure = {**medium_structure, "H4": structure_sequence("H4", "BULLISH")}
    assert calculate(medium_structure, liquidity={"M15": [sweep]}).reversal_confidence is ReversalConfidence.MEDIUM
    assert calculate(high_structure, liquidity={"M15": [sweep]}).reversal_confidence is ReversalConfidence.HIGH


def test_liquidity_map_tracks_distance_and_sweep_state():
    level = LiquidityEventData(
        NOW - timedelta(hours=1), "EURUSD", "H1", "LIQUIDITY_LEVEL", "HIGH", Decimal("1.2"),
        NOW - timedelta(hours=1), 80.0, {"level_type": "CONFIRMED_SWING_HIGH"},
    )
    sweep = LiquidityEventData(
        NOW, "EURUSD", "H1", "LIQUIDITY_SWEEP", "BEARISH", Decimal("1.19"), NOW, 80.0,
        {"level_type": "CONFIRMED_SWING_HIGH", "liquidity_level": "1.2"},
    )
    entry = calculate({}, liquidity={"H1": [level, sweep]}, available=("H1",)).liquidity_map[0]
    assert entry.timeframe == "H1" and entry.swept is True
    assert entry.distance_from_price == Decimal("0.1") and entry.sweep_timestamp == NOW


def test_d1_liquidity_includes_previous_week_and_month_levels():
    rows = deterministic_m15_candles(40, start=datetime(2026, 1, 1, tzinfo=timezone.utc))
    for index, candle in enumerate(rows):
        candle["timeframe"] = "D1"
        candle["timestamp"] = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    level_types = {level.level_type for level in LiquidityEngine().levels(rows)}
    assert {"PREVIOUS_WEEK_HIGH", "PREVIOUS_WEEK_LOW", "PREVIOUS_MONTH_HIGH", "PREVIOUS_MONTH_LOW"} <= level_types


def test_indicator_values_are_isolated_by_timeframe():
    d1 = deterministic_m15_candles(60)
    for index, candle in enumerate(d1):
        candle["timeframe"] = "D1"
        candle["timestamp"] = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    m15 = deterministic_m15_candles(60)
    engine = MTFIndicatorEngine()
    before = engine.calculate_matrix({"D1": d1, "M15": m15}, as_of=d1[-1]["timestamp"] + timedelta(days=1))
    for candle in m15:
        candle["close"] += Decimal("0.05")
        candle["high"] += Decimal("0.05")
    after = engine.calculate_matrix({"D1": d1, "M15": m15}, as_of=d1[-1]["timestamp"] + timedelta(days=1))
    assert before["D1"] == after["D1"]
    assert before["D1"].available is True


def test_indicator_confirmation_does_not_change_structural_bias():
    structure = {tf: structure_sequence(tf, "BEARISH") for tf in ("D1", "H4", "H1")}
    baseline = calculate(structure)
    indicators = empty_indicators()
    indicators["M15"] = replace(indicators["M15"], available=True, rsi=20.0, missing_reason=None)
    with_oversold_m15 = calculate(structure, indicators=indicators)
    assert with_oversold_m15.htf_bias == baseline.htf_bias
    assert with_oversold_m15.market_state == baseline.market_state


def test_future_structure_cannot_change_regime_at_as_of():
    base = {tf: structure_sequence(tf, "BEARISH") for tf in ("D1", "H4", "H1")}
    before = calculate(base)
    future = {tf: list(events) for tf, events in base.items()}
    future["H1"] += structure_sequence("H1", "BULLISH", at=NOW + timedelta(days=1))
    after = calculate(future)
    assert after.htf_bias == before.htf_bias
    assert after.market_state == before.market_state


def test_institutional_flow_integration_reports_ltf_conflict_without_signal():
    structure = {
        "D1": structure_sequence("D1", "BEARISH"),
        "H4": structure_sequence("H4", "BEARISH"),
        "H1": structure_sequence("H1", "BEARISH"),
        "M15": structure_sequence("M15", "BULLISH"),
    }
    institutional = InstitutionalFlowInput(
        cot_score=-70, bank_participation_score=-60,
        cme_volume_score=-40, cme_open_interest_score=-50,
    )
    snapshot = calculate(structure, institutional=institutional)
    assert snapshot.institutional_flow_score == -55.0
    assert snapshot.institutional_bias == "BEARISH"
    assert "INSTITUTIONAL_LTF_CONFLICT" in snapshot.institutional_conflicts
    assert snapshot.signal is None


def test_missing_m5_m1_are_explicit_and_regime_api_uses_database(client, db_session):
    for row in deterministic_m15_candles(5):
        CandleRepository(db_session).add(row)
    response = client.get("/api/regime", params={"symbol": "EURUSD"})
    assert response.status_code == 200
    payload = response.json()
    assert {"M5", "M1"} <= set(payload["trend_matrix"]["missing_timeframes"])
    assert payload["trend_matrix"]["timeframes"]["M15"]["role"] == "LIQUIDITY_SETUP"
    assert payload["signal"] is None


def test_strategy_regime_boundary_does_not_accept_raw_candles():
    parameters = tuple(inspect.signature(RegimeDrivenStrategy.evaluate).parameters)
    assert parameters == ("self", "snapshot")
