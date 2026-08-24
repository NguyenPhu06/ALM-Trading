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
    confirmation_timestamp: datetime | None
    swing_type: SwingType
    confirmed: bool = True
    calculation_version: str = "phase3.v1"


class SwingDetector:
    """Causal fractal swing detector.

    A point at index ``i`` is emitted only when candle ``i + right_bars`` is
    available. Ties are resolved conservatively: a swing must be the unique
    extreme in its complete confirmation window.
    """

    def __init__(
        self, left_bars: int = 2, right_bars: int = 2, *,
        minimum_distance: int = 1,
        minimum_price_move: Decimal | float | str = Decimal("0"),
    ):
        if left_bars < 1 or right_bars < 1:
            raise ValueError("left_bars and right_bars must be positive")
        if minimum_distance < 1:
            raise ValueError("minimum_distance must be positive")
        self.left_bars = left_bars
        self.right_bars = right_bars
        self.minimum_distance = minimum_distance
        self.minimum_price_move = Decimal(str(minimum_price_move))

    @staticmethod
    def _value(candle: Any, name: str) -> Any:
        return candle[name] if isinstance(candle, dict) else getattr(candle, name)

    def detect(
        self, candles: Sequence[Any], *, as_of_index: int | None = None,
        include_unconfirmed: bool = False,
    ) -> list[SwingPoint]:
        if not candles:
            return []
        candles = closed_candle_prefix(candles, as_of_index=as_of_index)
        available_end = len(candles) - 1
        if available_end < self.left_bars + self.right_bars and not include_unconfirmed:
            return []

        points: list[SwingPoint] = []
        last_by_type: dict[SwingType, SwingPoint] = {}
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
                candidate = SwingPoint(
                    timestamp, symbol, timeframe, high, index,
                    self._strength(high - second, high, self.left_bars + self.right_bars),
                    confirmation, SwingType.HIGH,
                )
                if self._accepted(candidate, last_by_type.get(SwingType.HIGH)):
                    points.append(candidate)
                    last_by_type[SwingType.HIGH] = candidate
            if low == min(lows) and lows.count(low) == 1:
                second = min(value for offset, value in enumerate(lows) if offset != self.left_bars)
                candidate = SwingPoint(
                    timestamp, symbol, timeframe, low, index,
                    self._strength(second - low, low, self.left_bars + self.right_bars),
                    confirmation, SwingType.LOW,
                )
                if self._accepted(candidate, last_by_type.get(SwingType.LOW)):
                    points.append(candidate)
                    last_by_type[SwingType.LOW] = candidate
        if include_unconfirmed:
            points.extend(self._unconfirmed(candles, last_candidate + 1, last_by_type))
        return sorted(points, key=lambda point: (
            point.confirmation_timestamp is None,
            point.confirmation_timestamp or point.timestamp,
            point.index, point.swing_type,
        ))

    def _unconfirmed(
        self, candles: Sequence[Any], start_index: int,
        last_by_type: dict[SwingType, SwingPoint],
    ) -> list[SwingPoint]:
        output: list[SwingPoint] = []
        for index in range(max(self.left_bars, start_index), len(candles)):
            left = candles[index - self.left_bars:index]
            timestamp = self._value(candles[index], "timestamp")
            symbol = str(self._value(candles[index], "symbol"))
            timeframe = str(self._value(candles[index], "timeframe"))
            high = Decimal(str(self._value(candles[index], "high")))
            low = Decimal(str(self._value(candles[index], "low")))
            candidates = []
            if high > max(Decimal(str(self._value(row, "high"))) for row in left):
                candidates.append(SwingPoint(timestamp, symbol, timeframe, high, index, 0.0, None, SwingType.HIGH, False))
            if low < min(Decimal(str(self._value(row, "low"))) for row in left):
                candidates.append(SwingPoint(timestamp, symbol, timeframe, low, index, 0.0, None, SwingType.LOW, False))
            output.extend(item for item in candidates if self._accepted(item, last_by_type.get(item.swing_type)))
        return output

    def _accepted(self, candidate: SwingPoint, previous: SwingPoint | None) -> bool:
        if previous is None:
            return True
        return (
            candidate.index - previous.index >= self.minimum_distance
            and abs(candidate.price - previous.price) >= self.minimum_price_move
        )

    @staticmethod
    def _strength(prominence: Decimal, price: Decimal, context_bars: int) -> float:
        relative = float(abs(prominence) / abs(price)) if price else 0.0
        return round(min(100.0, context_bars * 8.0 + relative * 100_000.0), 2)
