from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from features.candles import candle_close_time, closed_candle_prefix
from features.smc.models import FairValueGap


class FairValueGapDetector:
    def __init__(self, *, minimum_size: Decimal | float | str = Decimal("0")):
        self.minimum_size = Decimal(str(minimum_size))

    @staticmethod
    def _value(candle: Any, name: str) -> Any:
        return candle[name] if isinstance(candle, dict) else getattr(candle, name)

    def detect(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> list[FairValueGap]:
        visible = closed_candle_prefix(candles, as_of_index=as_of_index)
        output: list[FairValueGap] = []
        for index in range(2, len(visible)):
            first, third = visible[index - 2], visible[index]
            first_high = Decimal(str(self._value(first, "high")))
            first_low = Decimal(str(self._value(first, "low")))
            third_high = Decimal(str(self._value(third, "high")))
            third_low = Decimal(str(self._value(third, "low")))
            if third_low > first_high and third_low - first_high >= self.minimum_size:
                output.append(self._gap(visible, index, "BULLISH", third_low, first_high))
            if third_high < first_low and first_low - third_high >= self.minimum_size:
                output.append(self._gap(visible, index, "BEARISH", first_low, third_high))
        return output

    def _gap(
        self, candles: Sequence[Any], detected_index: int, direction: str,
        upper: Decimal, lower: Decimal,
    ) -> FairValueGap:
        size = upper - lower
        fill = Decimal("0")
        for candle in candles[detected_index + 1:]:
            if direction == "BULLISH":
                low = Decimal(str(self._value(candle, "low")))
                fill = max(fill, upper - max(lower, low))
            else:
                high = Decimal(str(self._value(candle, "high")))
                fill = max(fill, min(upper, high) - lower)
        percentage = min(100.0, float(fill / size) * 100.0) if size else 100.0
        filled = percentage >= 100.0
        state = "FILLED" if filled else "PARTIALLY_FILLED" if percentage > 0 else "OPEN"
        candle = candles[detected_index]
        return FairValueGap(
            candle_close_time(candle), str(self._value(candle, "symbol")),
            str(self._value(candle, "timeframe")), direction, upper, lower, size,
            filled, round(percentage, 2), state,
        )
