from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from features.structure import BreakMode, MarketStructureEngine, SwingDetector
from features.candles import candle_close_time


BASE = datetime(2026, 8, 20, tzinfo=timezone.utc)


def candles(rows, *, start=BASE, timeframe="M15"):
    result = []
    for index, (open_, high, low, close) in enumerate(rows):
        result.append({
            "timestamp": start + timedelta(minutes=15 * index),
            "symbol": "EURUSD", "timeframe": timeframe,
            "open": Decimal(str(open_)), "high": Decimal(str(high)),
            "low": Decimal(str(low)), "close": Decimal(str(close)), "volume": Decimal("1"),
        })
    return result


STRUCTURE_ROWS = [
    (10, 10.5, 9.5, 10),
    (10, 12, 10, 11.5),       # swing high
    (10, 11, 8, 9),           # swing low; confirms high
    (11, 14, 10, 13),         # HH and bullish break
    (10, 12, 9, 10),          # HL
    (11, 13, 10, 12),         # LH
    (9, 11, 7, 8),            # LL / bearish break
    (8, 10, 8, 9),
]


def test_swing_detection_requires_right_confirmation_bar():
    rows = candles([(10, 11, 9, 10), (10, 13, 10, 12), (12, 12.5, 9, 10)])
    detector = SwingDetector(left_bars=1, right_bars=1)
    assert detector.detect(rows, as_of_index=1) == []
    swings = detector.detect(rows, as_of_index=2)
    high = next(point for point in swings if point.swing_type == "SWING_HIGH")
    assert high.index == 1
    assert high.confirmation_timestamp == candle_close_time(rows[2])


def test_market_structure_classifies_hh_hl_lh_ll():
    events = MarketStructureEngine(swing_left_bars=1, swing_right_bars=1).calculate(candles(STRUCTURE_ROWS))
    kinds = {event.event_type for event in events}
    assert {"HH", "HL", "LH", "LL"} <= kinds


def test_bullish_bos_uses_confirmed_swing_high():
    events = MarketStructureEngine(swing_left_bars=1, swing_right_bars=1).calculate(candles(STRUCTURE_ROWS[:5]))
    bos = next(event for event in events if event.event_type == "BULLISH_BOS")
    assert bos.metadata["broken_level"] == "12"
    assert bos.metadata["level_confirmation_timestamp"] <= bos.event_timestamp.isoformat()


def test_close_break_does_not_mark_wick_only_bos():
    rows = candles([(10, 11, 9, 10), (10, 12, 10, 11), (11, 11.5, 9, 10), (11, 12.2, 10, 11.8)])
    close_events = MarketStructureEngine(swing_left_bars=1, swing_right_bars=1).calculate(rows)
    wick_events = MarketStructureEngine(swing_left_bars=1, swing_right_bars=1, break_mode=BreakMode.WICK_BREAK).calculate(rows)
    assert not any(event.event_type == "BULLISH_BOS" for event in close_events)
    assert any(event.event_type == "BULLISH_BOS" for event in wick_events)


def test_bearish_bos_and_bearish_choch():
    events = MarketStructureEngine(swing_left_bars=1, swing_right_bars=1).calculate(candles(STRUCTURE_ROWS))
    assert any(event.event_type == "BEARISH_CHOCH" for event in events)
    # A neutral/bearish continuation fixture produces a BOS through a confirmed low.
    continuation = candles([(10, 11, 9, 10), (10, 12, 10, 11), (10, 11, 8, 9), (9, 11, 9, 10), (8, 10, 7, 7.5)])
    assert any(event.event_type == "BEARISH_BOS" for event in MarketStructureEngine(swing_left_bars=1, swing_right_bars=1).calculate(continuation))


def test_bullish_choch_from_bearish_structure():
    rows = candles([
        (10, 10.5, 9, 10), (10, 14, 10, 13), (10, 12, 8, 9),
        (9, 13, 9, 12), (9, 11, 7, 8), (8, 14, 8, 13.5),
    ])
    events = MarketStructureEngine(swing_left_bars=1, swing_right_bars=1).calculate(rows)
    choch = next(event for event in events if event.event_type == "BULLISH_CHOCH")
    assert choch.metadata["previous_structure"] == "BEARISH"
    assert choch.metadata["new_direction"] == "BULLISH"


def test_equal_high_and_equal_low_use_tolerance_not_exact_equality():
    rows = candles([
        (10, 10.5, 9.5, 10), (10, 12, 10, 11), (10, 11, 8, 9),
        (9, 12.00002, 10, 11), (10, 11, 8.00002, 9), (9, 10, 9, 9.5),
    ])
    events = MarketStructureEngine(
        swing_left_bars=1, swing_right_bars=1,
        equal_level_tolerance_points=3, point_size="0.00001",
    ).calculate(rows)
    assert any(event.event_type == "EQUAL_HIGH" for event in events)
    assert any(event.event_type == "EQUAL_LOW" for event in events)


def test_future_extension_cannot_change_past_decisions():
    prefix = candles(STRUCTURE_ROWS[:5])
    future = candles(STRUCTURE_ROWS, start=BASE)
    engine = MarketStructureEngine(swing_left_bars=1, swing_right_bars=1)
    cutoff = candle_close_time(prefix[-1])
    before = [(e.event_timestamp, e.event_type, e.price) for e in engine.calculate(prefix)]
    after = [(e.event_timestamp, e.event_type, e.price) for e in engine.calculate(future) if e.event_timestamp <= cutoff]
    assert after == before
