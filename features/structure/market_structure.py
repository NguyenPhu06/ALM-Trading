from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Sequence

from features.candles import candle_close_time, closed_candle_prefix
from features.structure.swing_detector import SwingDetector, SwingPoint, SwingType


logger = logging.getLogger(__name__)


class BreakMode(StrEnum):
    CLOSE_BREAK = "CLOSE_BREAK"
    WICK_BREAK = "WICK_BREAK"


class StructureBias(StrEnum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"


@dataclass(frozen=True, slots=True)
class StructureEventData:
    event_timestamp: datetime
    symbol: str
    timeframe: str
    event_type: str
    direction: str | None
    price: Decimal
    confirmation_timestamp: datetime | None = None
    strength: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def confirmation_status(self) -> str:
        return "CONFIRMED" if self.confirmation_timestamp is None or self.confirmation_timestamp <= self.event_timestamp else "PENDING"


class MarketStructureEngine:
    def __init__(
        self,
        *,
        swing_left_bars: int = 2,
        swing_right_bars: int = 2,
        break_mode: BreakMode | str = BreakMode.CLOSE_BREAK,
        equal_level_tolerance_points: float = 3.0,
        point_size: Decimal | float | str = Decimal("0.00001"),
    ):
        self.swing_detector = SwingDetector(swing_left_bars, swing_right_bars)
        self.break_mode = BreakMode(break_mode)
        self.equal_tolerance = Decimal(str(equal_level_tolerance_points)) * Decimal(str(point_size))

    @staticmethod
    def _value(candle: Any, name: str) -> Any:
        return candle[name] if isinstance(candle, dict) else getattr(candle, name)

    def calculate(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> list[StructureEventData]:
        if not candles:
            return []
        visible = closed_candle_prefix(candles, as_of_index=as_of_index)
        swings = self.swing_detector.detect(visible)
        confirmations: dict[datetime, list[SwingPoint]] = {}
        for swing in swings:
            confirmations.setdefault(swing.confirmation_timestamp, []).append(swing)

        events: list[StructureEventData] = []
        previous_high: SwingPoint | None = None
        previous_low: SwingPoint | None = None
        active_high: SwingPoint | None = None
        active_low: SwingPoint | None = None
        broken: set[tuple[str, int]] = set()
        last_high_class: str | None = None
        last_low_class: str | None = None
        direction = "NEUTRAL"

        for candle_index, candle in enumerate(visible):
            timestamp = candle_close_time(candle)
            symbol = str(self._value(candle, "symbol"))
            timeframe = str(self._value(candle, "timeframe"))

            for swing in confirmations.get(timestamp, []):
                previous = previous_high if swing.swing_type is SwingType.HIGH else previous_low
                classification = None
                if previous is not None:
                    if swing.swing_type is SwingType.HIGH:
                        classification = "HH" if swing.price > previous.price else "LH" if swing.price < previous.price else None
                    else:
                        classification = "HL" if swing.price > previous.price else "LL" if swing.price < previous.price else None

                events.append(StructureEventData(
                    event_timestamp=timestamp,
                    symbol=swing.symbol,
                    timeframe=swing.timeframe,
                    event_type=swing.swing_type.value,
                    direction="BEARISH" if swing.swing_type is SwingType.HIGH else "BULLISH",
                    price=swing.price,
                    confirmation_timestamp=swing.confirmation_timestamp,
                    strength=swing.strength,
                    metadata={"swing_timestamp": swing.timestamp.isoformat(), "index": swing.index},
                ))
                if classification:
                    events.append(StructureEventData(
                        timestamp, swing.symbol, swing.timeframe, classification,
                        "BULLISH" if classification in {"HH", "HL"} else "BEARISH",
                        swing.price, swing.confirmation_timestamp, swing.strength,
                        {"swing_timestamp": swing.timestamp.isoformat(), "previous_price": str(previous.price)},
                    ))
                    if swing.swing_type is SwingType.HIGH:
                        last_high_class = classification
                    else:
                        last_low_class = classification

                if previous is not None and abs(swing.price - previous.price) <= self.equal_tolerance:
                    equal_type = "EQUAL_HIGH" if swing.swing_type is SwingType.HIGH else "EQUAL_LOW"
                    events.append(StructureEventData(
                        timestamp, swing.symbol, swing.timeframe, equal_type, None, swing.price,
                        swing.confirmation_timestamp, min(swing.strength, previous.strength),
                        {"first_price": str(previous.price), "second_price": str(swing.price),
                         "tolerance": str(self.equal_tolerance), "touches": 2},
                    ))

                if swing.swing_type is SwingType.HIGH:
                    previous_high = active_high = swing
                else:
                    previous_low = active_low = swing

                if last_high_class == "HH" and last_low_class == "HL":
                    direction = "BULLISH"
                elif last_high_class == "LH" and last_low_class == "LL":
                    direction = "BEARISH"

            high_source = Decimal(str(self._value(candle, "close"))) if self.break_mode is BreakMode.CLOSE_BREAK else Decimal(str(self._value(candle, "high")))
            low_source = Decimal(str(self._value(candle, "close"))) if self.break_mode is BreakMode.CLOSE_BREAK else Decimal(str(self._value(candle, "low")))
            close = Decimal(str(self._value(candle, "close")))

            if active_high and candle_index > active_high.index and ("HIGH", active_high.index) not in broken and high_source > active_high.price:
                previous_structure = direction
                event_type = "BULLISH_CHOCH" if direction == "BEARISH" else "BULLISH_BOS"
                events.append(self._break_event(
                    timestamp, symbol, timeframe, event_type, close, active_high,
                    previous_structure, "BULLISH", candle,
                ))
                broken.add(("HIGH", active_high.index))
                if previous_structure != "NEUTRAL":
                    direction = "BULLISH"

            if active_low and candle_index > active_low.index and ("LOW", active_low.index) not in broken and low_source < active_low.price:
                previous_structure = direction
                event_type = "BEARISH_CHOCH" if direction == "BULLISH" else "BEARISH_BOS"
                events.append(self._break_event(
                    timestamp, symbol, timeframe, event_type, close, active_low,
                    previous_structure, "BEARISH", candle,
                ))
                broken.add(("LOW", active_low.index))
                if previous_structure != "NEUTRAL":
                    direction = "BEARISH"

        logger.info("structure calculation: candles=%d swings=%d events=%d", len(visible), len(swings), len(events))
        return sorted(events, key=lambda item: item.event_timestamp)

    def _break_event(
        self,
        timestamp: datetime,
        symbol: str,
        timeframe: str,
        event_type: str,
        price: Decimal,
        level: SwingPoint,
        previous_structure: str,
        new_direction: str,
        candle: Any,
    ) -> StructureEventData:
        open_ = Decimal(str(self._value(candle, "open")))
        high = Decimal(str(self._value(candle, "high")))
        low = Decimal(str(self._value(candle, "low")))
        displacement = float(abs(price - open_) / (high - low)) if high > low else 0.0
        return StructureEventData(
            timestamp, symbol, timeframe, event_type, new_direction, price,
            level.confirmation_timestamp, level.strength,
            {
                "previous_structure": previous_structure,
                "broken_level": str(level.price),
                "new_direction": new_direction,
                "break_mode": self.break_mode.value,
                "level_confirmation_timestamp": level.confirmation_timestamp.isoformat(),
                "displacement": round(displacement, 4),
            },
        )

    @staticmethod
    def bias(events: Sequence[StructureEventData]) -> tuple[StructureBias, float]:
        score = 0.0
        for event in events:
            sign = 1.0 if event.direction == "BULLISH" else -1.0 if event.direction == "BEARISH" else 0.0
            if event.event_type.endswith("BOS"):
                score += sign * 30.0
            elif event.event_type.endswith("CHOCH"):
                score += sign * 24.0
            elif event.event_type in {"HH", "LL"}:
                score += sign * 12.0
            elif event.event_type in {"HL", "LH"}:
                score += sign * 8.0
            if event.event_type.endswith(("BOS", "CHOCH")):
                score += sign * min(10.0, float(event.metadata.get("displacement", 0)) * 10.0)
        score = max(-100.0, min(100.0, score))
        if score >= 60:
            bias = StructureBias.STRONG_BULLISH
        elif score >= 20:
            bias = StructureBias.BULLISH
        elif score <= -60:
            bias = StructureBias.STRONG_BEARISH
        elif score <= -20:
            bias = StructureBias.BEARISH
        else:
            bias = StructureBias.NEUTRAL
        return bias, round(score, 2)
