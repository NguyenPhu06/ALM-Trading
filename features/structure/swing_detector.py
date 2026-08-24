from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Sequence

from features.candles import candle_close_time, closed_candle_prefix


class SwingType(StrEnum):
    HIGH = "SWING_HIGH"
    LOW = "SWING_LOW"


@dataclass(frozen=True, slots=True)
class SwingPoint:
    timestamp: datetime
    symbol: str
    timeframe: str
    price: Decimal
    index: int
    strength: float
    confirmation_timestamp: datetime
    swing_type: SwingType


class SwingDetector:
    """Causal fractal swing detector.

    A point at index ``i`` is emitted only when candle ``i + right_bars`` is
    available. Ties are resolved conservatively: a swing must be the unique
    extreme in its complete confirmation window.
    """

    def __init__(self, left_bars: int = 2, right_bars: int = 2):
        if left_bars < 1 or right_bars < 1:
            raise ValueError("left_bars and right_bars must be positive")
        self.left_bars = left_bars
        self.right_bars = right_bars

    @staticmethod
    def _value(candle: Any, name: str) -> Any:
        return candle[name] if isinstance(candle, dict) else getattr(candle, name)

    def detect(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> list[SwingPoint]:
        if not candles:
            return []
        candles = closed_candle_prefix(candles, as_of_index=as_of_index)
        available_end = len(candles) - 1
        if available_end < self.left_bars + self.right_bars:
            return []

        points: list[SwingPoint] = []
        last_candidate = available_end - self.right_bars
        for index in range(self.left_bars, last_candidate + 1):
            start = index - self.left_bars
            end = index + self.right_bars
            window = candles[start : end + 1]
            high = Decimal(str(self._value(candles[index], "high")))
            low = Decimal(str(self._value(candles[index], "low")))
            highs = [Decimal(str(self._value(row, "high"))) for row in window]
            lows = [Decimal(str(self._value(row, "low"))) for row in window]
            confirmation = candle_close_time(candles[end])
            symbol = str(self._value(candles[index], "symbol"))
            timeframe = str(self._value(candles[index], "timeframe"))
            timestamp = self._value(candles[index], "timestamp")

            if high == max(highs) and highs.count(high) == 1:
                second = max(value for offset, value in enumerate(highs) if offset != self.left_bars)
                points.append(SwingPoint(
                    timestamp, symbol, timeframe, high, index,
                    self._strength(high - second, high, self.left_bars + self.right_bars),
                    confirmation, SwingType.HIGH,
                ))
            if low == min(lows) and lows.count(low) == 1:
                second = min(value for offset, value in enumerate(lows) if offset != self.left_bars)
                points.append(SwingPoint(
                    timestamp, symbol, timeframe, low, index,
                    self._strength(second - low, low, self.left_bars + self.right_bars),
                    confirmation, SwingType.LOW,
                ))
        return sorted(points, key=lambda point: (point.confirmation_timestamp, point.index, point.swing_type))

    @staticmethod
    def _strength(prominence: Decimal, price: Decimal, context_bars: int) -> float:
        relative = float(abs(prominence) / abs(price)) if price else 0.0
        return round(min(100.0, context_bars * 8.0 + relative * 100_000.0), 2)
