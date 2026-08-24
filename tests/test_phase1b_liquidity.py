from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from features.liquidity import LiquidityEngine
from features.session import SessionEngine, SessionName


BASE = datetime(2026, 8, 20, tzinfo=timezone.utc)


def make(rows, timestamps=None):
    timestamps = timestamps or [BASE + timedelta(minutes=15 * i) for i in range(len(rows))]
    return [{
        "timestamp": timestamps[i], "symbol": "EURUSD", "timeframe": "M15",
        "open": Decimal(str(row[0])), "high": Decimal(str(row[1])),
        "low": Decimal(str(row[2])), "close": Decimal(str(row[3])), "volume": Decimal("1"),
    } for i, row in enumerate(rows)]


def test_bearish_liquidity_sweep_of_confirmed_high():
    rows = make([(10, 11, 9, 10), (10, 12, 10, 11), (11, 11.5, 9, 10), (11.7, 12.2, 11, 11.8)])
    events = LiquidityEngine(swing_left_bars=1, swing_right_bars=1).calculate(rows)
    sweep = next(e for e in events if e.event_type == "LIQUIDITY_SWEEP" and e.metadata["level_type"] == "CONFIRMED_SWING_HIGH")
    assert sweep.direction == "BEARISH"
    assert sweep.metadata["close_back_inside"] is True
    assert Decimal(sweep.metadata["penetration"]) > 0


def test_bullish_liquidity_sweep_of_confirmed_low():
    rows = make([(10, 11, 9, 10), (10, 11, 8, 9), (9, 12, 9, 11), (8.3, 9, 7.8, 8.2)])
    events = LiquidityEngine(swing_left_bars=1, swing_right_bars=1).calculate(rows)
    sweep = next(e for e in events if e.event_type == "LIQUIDITY_SWEEP" and e.metadata["level_type"] == "CONFIRMED_SWING_LOW")
    assert sweep.direction == "BULLISH"
    assert Decimal(sweep.metadata["rejection"]) > 0


def test_previous_day_high_and_low_are_known_next_day_only():
    times = [
        datetime(2026, 8, 20, 22, tzinfo=timezone.utc),
        datetime(2026, 8, 20, 23, tzinfo=timezone.utc),
        datetime(2026, 8, 21, 0, tzinfo=timezone.utc),
    ]
    rows = make([(10, 12, 9, 11), (11, 13, 8, 10), (10, 11, 9, 10)], times)
    levels = LiquidityEngine(swing_left_bars=1, swing_right_bars=1).levels(rows)
    pdh = next(level for level in levels if level.level_type == "PREVIOUS_DAY_HIGH")
    pdl = next(level for level in levels if level.level_type == "PREVIOUS_DAY_LOW")
    assert pdh.price == Decimal("13") and pdl.price == Decimal("8")
    assert pdh.event_timestamp == times[2] + timedelta(minutes=15) == pdl.event_timestamp


def test_session_high_low_are_running_not_future_final_values():
    times = [BASE + timedelta(hours=hour) for hour in (0, 1, 2)]
    rows = make([(10, 11, 9, 10), (10, 13, 8, 12), (12, 14, 7, 13)], times)
    levels = [level for level in SessionEngine().levels(rows) if level.is_current]
    assert (levels[0].high, levels[0].low) == (11.0, 9.0)
    assert (levels[1].high, levels[1].low) == (13.0, 8.0)
    assert (levels[2].high, levels[2].low) == (14.0, 7.0)


def test_previous_session_high_and_low_only_appear_after_transition():
    times = [
        datetime(2026, 8, 20, 8, tzinfo=timezone.utc),
        datetime(2026, 8, 20, 9, tzinfo=timezone.utc),
        datetime(2026, 8, 20, 13, tzinfo=timezone.utc),
    ]
    rows = make([(10, 12, 9, 11), (11, 13, 8, 12), (12, 12.5, 10, 11)], times)
    previous = [level for level in SessionEngine().levels(rows) if not level.is_current]
    assert previous
    assert previous[0].event_timestamp == times[2] + timedelta(minutes=15)
    assert (previous[0].high, previous[0].low) == (13.0, 8.0)


def test_session_and_even_hour_features():
    engine = SessionEngine()
    features = engine.time_features(datetime(2026, 8, 20, 14, 0, tzinfo=timezone.utc))
    assert features.session is SessionName.OVERLAP
    assert features.is_even_hour is True
    assert engine.time_features(datetime(2026, 8, 20, 14, 15, tzinfo=timezone.utc)).is_even_hour is False


def test_liquidity_strength_is_deterministic_and_bounded():
    args = (Decimal("0.001"), Decimal("1.1"), 3, 10, "H4", True, 80.0, 20.0)
    score = LiquidityEngine.strength_score(*args)
    assert score == LiquidityEngine.strength_score(*args)
    assert 0 <= score <= 100
