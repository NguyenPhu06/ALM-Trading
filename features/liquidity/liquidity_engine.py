from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from features.candles import candle_close_time, closed_candle_prefix
from features.session import SessionEngine, SessionName
from features.structure.swing_detector import SwingDetector, SwingType


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LiquidityLevel:
    event_timestamp: datetime
    symbol: str
    timeframe: str
    level_type: str
    side: str
    price: Decimal
    strength: float
    touches: int = 1
    swing_strength: float = 0.0
    equal_level: bool = False
    session_relevance: float = 0.0
    calculation_version: str = "phase3.v1"


@dataclass(frozen=True, slots=True)
class LiquidityEventData:
    event_timestamp: datetime
    symbol: str
    timeframe: str
    event_type: str
    direction: str | None
    price: Decimal
    confirmation_timestamp: datetime | None = None
    strength: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    calculation_version: str = "phase3.v1"


@dataclass(frozen=True, slots=True)
class LiquidityMapEntry:
    price: Decimal
    type: str
    timeframe: str
    strength: float
    created_at: datetime
    swept: bool
    swept_at: datetime | None
    side: str
    symbol: str
    calculation_version: str = "phase3.v1"


class LiquidityEngine:
    TIMEFRAME_WEIGHT = {"M1": 5, "M5": 8, "M15": 12, "M30": 15, "H1": 20, "H4": 28, "D1": 35, "W1": 40, "MN1": 45}

    def __init__(
        self,
        *,
        swing_left_bars: int = 2,
        swing_right_bars: int = 2,
        equal_level_tolerance_points: float = 3.0,
        point_size: Decimal | float | str = Decimal("0.00001"),
        minimum_rejection_ratio: float = 0.15,
        minimum_pool_touches: int = 2,
        session_engine: SessionEngine | None = None,
    ):
        self.swing_detector = SwingDetector(swing_left_bars, swing_right_bars)
        self.tolerance = Decimal(str(equal_level_tolerance_points)) * Decimal(str(point_size))
        self.minimum_rejection_ratio = minimum_rejection_ratio
        self.minimum_pool_touches = max(2, minimum_pool_touches)
        self.session_engine = session_engine or SessionEngine()

    @staticmethod
    def _value(candle: Any, name: str) -> Any:
        return candle[name] if isinstance(candle, dict) else getattr(candle, name)

    def calculate(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> list[LiquidityEventData]:
        if not candles:
            return []
        visible = closed_candle_prefix(candles, as_of_index=as_of_index)
        levels = self.levels(visible)
        by_time: dict[datetime, list[LiquidityLevel]] = {}
        for level in levels:
            by_time.setdefault(level.event_timestamp, []).append(level)

        events: list[LiquidityEventData] = []
        active: list[tuple[LiquidityLevel, int]] = []
        swept: set[tuple[str, datetime, Decimal]] = set()
        for candle_index, candle in enumerate(visible):
            timestamp = candle_close_time(candle)
            high = Decimal(str(self._value(candle, "high")))
            low = Decimal(str(self._value(candle, "low")))
            close = Decimal(str(self._value(candle, "close")))
            open_ = Decimal(str(self._value(candle, "open")))

            # A level becomes usable after it is known at this candle close, never before.
            for level, created_index in list(active):
                key = (level.level_type, level.event_timestamp, level.price)
                if key in swept or timestamp <= level.event_timestamp:
                    continue
                candle_range = high - low
                if level.side == "HIGH" and high > level.price and close < level.price:
                    penetration = high - level.price
                    rejection = high - max(open_, close)
                    ratio = float(rejection / candle_range) if candle_range else 0.0
                    if ratio >= self.minimum_rejection_ratio:
                        events.append(self._sweep(level, timestamp, close, "BEARISH", penetration, rejection, ratio, candle_index - created_index))
                        swept.add(key)
                elif level.side == "LOW" and low < level.price and close > level.price:
                    penetration = level.price - low
                    rejection = min(open_, close) - low
                    ratio = float(rejection / candle_range) if candle_range else 0.0
                    if ratio >= self.minimum_rejection_ratio:
                        events.append(self._sweep(level, timestamp, close, "BULLISH", penetration, rejection, ratio, candle_index - created_index))
                        swept.add(key)

            for level in by_time.get(timestamp, []):
                events.append(LiquidityEventData(
                    timestamp, level.symbol, level.timeframe, "LIQUIDITY_LEVEL", level.side,
                    level.price, timestamp, level.strength,
                    {"level_type": level.level_type, "touches": level.touches,
                     "equal_level": level.equal_level, "session_relevance": level.session_relevance},
                ))
                active.append((level, candle_index))

        logger.info("liquidity calculation: candles=%d levels=%d events=%d", len(visible), len(levels), len(events))
        return sorted(events, key=lambda item: item.event_timestamp)

    def levels(self, candles: Sequence[Any]) -> list[LiquidityLevel]:
        if not candles:
            return []
        levels: list[LiquidityLevel] = []
        swings = self.swing_detector.detect(candles)
        previous_by_side: dict[str, Any] = {}
        close_by_time = {candle_close_time(row): Decimal(str(self._value(row, "close"))) for row in candles}
        for swing in swings:
            side = "HIGH" if swing.swing_type is SwingType.HIGH else "LOW"
            previous = previous_by_side.get(side)
            equal = previous is not None and abs(swing.price - previous.price) <= self.tolerance
            level_type = "EQUAL_HIGH" if equal and side == "HIGH" else "EQUAL_LOW" if equal else f"CONFIRMED_SWING_{side}"
            touches = 2 if equal else 1
            strength = self.strength_score(
                distance=abs(close_by_time[swing.confirmation_timestamp] - swing.price),
                current_price=close_by_time[swing.confirmation_timestamp], touches=touches,
                age_bars=0, timeframe=swing.timeframe, equal_level=equal,
                swing_strength=swing.strength, session_relevance=0,
            )
            levels.append(LiquidityLevel(
                swing.confirmation_timestamp, swing.symbol, swing.timeframe, level_type, side,
                swing.price, strength, touches, swing.strength, equal, 0,
            ))
            previous_by_side[side] = swing

        for side in ("HIGH", "LOW"):
            side_swings = [swing for swing in swings if (swing.swing_type is SwingType.HIGH) == (side == "HIGH")]
            cluster: list[Any] = []
            for swing in side_swings:
                if cluster and abs(swing.price - cluster[-1].price) > self.tolerance:
                    self._append_pool(levels, cluster, side, close_by_time)
                    cluster = []
                cluster.append(swing)
            self._append_pool(levels, cluster, side, close_by_time)

        symbol = str(self._value(candles[0], "symbol"))
        timeframe = str(self._value(candles[0], "timeframe"))
        previous_date = None
        day_high = day_low = None
        for candle in candles:
            open_timestamp = self._value(candle, "timestamp")
            timestamp = candle_close_time(candle)
            date = open_timestamp.date()
            high = Decimal(str(self._value(candle, "high")))
            low = Decimal(str(self._value(candle, "low")))
            if previous_date is not None and date != previous_date:
                assert day_high is not None and day_low is not None
                for level_type, side, price in (("PREVIOUS_DAY_HIGH", "HIGH", day_high), ("PREVIOUS_DAY_LOW", "LOW", day_low)):
                    levels.append(LiquidityLevel(
                        timestamp, symbol, timeframe, level_type, side, price,
                        self.strength_score(abs(Decimal(str(self._value(candle, "close"))) - price), Decimal(str(self._value(candle, "close"))), 1, 0, "D1", False, 0, 20),
                        session_relevance=20,
                    ))
                day_high, day_low = high, low
            else:
                day_high = high if day_high is None else max(day_high, high)
                day_low = low if day_low is None else min(day_low, low)
            previous_date = date

        for period_name, key_function, reference_timeframe, relevance in (
            ("WEEK", lambda value: value.isocalendar()[:2], "W1", 25),
            ("MONTH", lambda value: (value.year, value.month), "MN1", 30),
        ):
            previous_key = None
            period_high = period_low = None
            for candle in candles:
                open_timestamp = self._value(candle, "timestamp")
                period_key = key_function(open_timestamp.date())
                high = Decimal(str(self._value(candle, "high")))
                low = Decimal(str(self._value(candle, "low")))
                close = Decimal(str(self._value(candle, "close")))
                if previous_key is not None and period_key != previous_key:
                    assert period_high is not None and period_low is not None
                    for suffix, side, price in (("HIGH", "HIGH", period_high), ("LOW", "LOW", period_low)):
                        levels.append(LiquidityLevel(
                            candle_close_time(candle), symbol, timeframe,
                            f"PREVIOUS_{period_name}_{suffix}", side, price,
                            self.strength_score(abs(close - price), close, 1, 0, reference_timeframe, False, 0, relevance),
                            session_relevance=relevance,
                        ))
                    period_high, period_low = high, low
                else:
                    period_high = high if period_high is None else max(period_high, high)
                    period_low = low if period_low is None else min(period_low, low)
                previous_key = period_key

        session_levels = self.session_engine.levels(candles)
        last_by_key: dict[tuple[str, SessionName, str], Decimal] = {}
        for item in session_levels:
            relevance = 15 if item.session in {SessionName.LONDON, SessionName.NEW_YORK, SessionName.OVERLAP} else 8
            prefix = "CURRENT_SESSION" if item.is_current else "PREVIOUS_SESSION"
            close = close_by_time[item.event_timestamp]
            for suffix, side, price in (("HIGH", "HIGH", Decimal(str(item.high))), ("LOW", "LOW", Decimal(str(item.low)))):
                key = (prefix, item.session, suffix)
                if last_by_key.get(key) == price:
                    continue
                levels.append(LiquidityLevel(
                    item.event_timestamp, symbol, timeframe, f"{prefix}_{suffix}", side, price,
                    self.strength_score(abs(close - price), close, 1, 0, timeframe, False, 0, relevance),
                    session_relevance=relevance,
                ))
                last_by_key[key] = price
        return sorted(levels, key=lambda item: item.event_timestamp)

    def liquidity_map(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> list[LiquidityMapEntry]:
        visible = closed_candle_prefix(candles, as_of_index=as_of_index)
        return self.map_from_events(self.calculate(visible))

    @staticmethod
    def map_from_events(events: Sequence[LiquidityEventData]) -> list[LiquidityMapEntry]:
        levels = [event for event in events if event.event_type == "LIQUIDITY_LEVEL"]
        sweeps = [event for event in events if event.event_type == "LIQUIDITY_SWEEP"]
        output = []
        for level in levels:
            sweep = next((
                event for event in sweeps
                if event.event_timestamp > level.event_timestamp
                and event.metadata.get("level_type") == level.metadata.get("level_type")
                and Decimal(str(event.metadata.get("liquidity_level"))) == level.price
            ), None)
            output.append(LiquidityMapEntry(
                level.price, str(level.metadata.get("level_type")), level.timeframe, float(level.strength or 0),
                level.event_timestamp, sweep is not None, sweep.event_timestamp if sweep else None,
                str(level.direction), level.symbol,
            ))
        return output

    def _append_pool(
        self, levels: list[LiquidityLevel], cluster: list[Any], side: str,
        close_by_time: dict[datetime, Decimal],
    ) -> None:
        if len(cluster) < self.minimum_pool_touches:
            return
        latest = cluster[-1]
        price = sum((item.price for item in cluster), Decimal("0")) / len(cluster)
        close = close_by_time[latest.confirmation_timestamp]
        levels.append(LiquidityLevel(
            latest.confirmation_timestamp, latest.symbol, latest.timeframe,
            "BUY_SIDE_LIQUIDITY_POOL" if side == "HIGH" else "SELL_SIDE_LIQUIDITY_POOL",
            side, price,
            self.strength_score(abs(close - price), close, len(cluster), 0, latest.timeframe, True,
                                max(item.strength for item in cluster), 0),
            len(cluster), max(item.strength for item in cluster), True, 0,
        ))

    def _sweep(
        self, level: LiquidityLevel, timestamp: datetime, close: Decimal,
        direction: str, penetration: Decimal, rejection: Decimal, rejection_ratio: float,
        age_bars: int,
    ) -> LiquidityEventData:
        strength = self.strength_score(
            abs(close - level.price), close, level.touches, age_bars, level.timeframe,
            level.equal_level, level.swing_strength, level.session_relevance,
        )
        return LiquidityEventData(
            timestamp, level.symbol, level.timeframe, "LIQUIDITY_SWEEP", direction, close,
            timestamp, strength,
            {"sweep_type": f"{direction}_LIQUIDITY_SWEEP", "level_type": level.level_type,
             "liquidity_side": "BUY_SIDE" if level.side == "HIGH" else "SELL_SIDE",
             "liquidity_level": str(level.price), "penetration": str(penetration),
             "rejection": str(rejection), "rejection_ratio": round(rejection_ratio, 4),
             "close_back_inside": True, "level_known_at": level.event_timestamp.isoformat(),
             "age_bars": age_bars},
        )

    @classmethod
    def strength_score(
        cls, distance: Decimal, current_price: Decimal, touches: int, age_bars: int,
        timeframe: str, equal_level: bool, swing_strength: float, session_relevance: float,
    ) -> float:
        relative_distance = float(distance / abs(current_price)) if current_price else 1.0
        distance_score = max(0.0, 20.0 - min(20.0, relative_distance * 2000.0))
        touch_score = min(15.0, max(0, touches - 1) * 7.5)
        age_score = min(10.0, age_bars * 0.5)
        timeframe_score = float(cls.TIMEFRAME_WEIGHT.get(timeframe, 5)) * 0.5
        equal_score = 12.0 if equal_level else 0.0
        swing_score = min(15.0, max(0.0, swing_strength) * 0.15)
        session_score = min(10.0, max(0.0, session_relevance) * 0.5)
        return round(min(100.0, distance_score + touch_score + age_score + timeframe_score + equal_score + swing_score + session_score), 2)
