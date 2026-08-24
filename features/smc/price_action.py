from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from features.candles import candle_close_time, closed_candle_prefix
from features.indicators.mtf_indicators import MTFIndicatorEngine
from features.smc.models import DisplacementFeature, OrderBlock, RejectionFeature


class DisplacementDetector:
    def __init__(self, *, atr_period: int = 14, minimum_atr_ratio: float = 1.5, minimum_body_ratio: float = 0.6):
        self.atr_period = atr_period
        self.minimum_atr_ratio = minimum_atr_ratio
        self.minimum_body_ratio = minimum_body_ratio

    @staticmethod
    def _value(candle: Any, name: str, default: Any = None) -> Any:
        return candle.get(name, default) if isinstance(candle, dict) else getattr(candle, name, default)

    def detect(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> list[DisplacementFeature]:
        visible = closed_candle_prefix(candles, as_of_index=as_of_index)
        output = []
        for index, candle in enumerate(visible):
            open_ = Decimal(str(self._value(candle, "open")))
            close = Decimal(str(self._value(candle, "close")))
            high = Decimal(str(self._value(candle, "high")))
            low = Decimal(str(self._value(candle, "low")))
            body, candle_range = abs(close - open_), high - low
            prefix = visible[:index + 1]
            highs = [float(self._value(row, "high")) for row in prefix]
            lows = [float(self._value(row, "low")) for row in prefix]
            closes = [float(self._value(row, "close")) for row in prefix]
            atr = MTFIndicatorEngine._atr(highs, lows, closes, self.atr_period)
            atr_ratio = float(candle_range) / atr if atr else None
            volumes = [Decimal(str(self._value(row, "volume"))) for row in visible[max(0, index - self.atr_period):index] if self._value(row, "volume") is not None]
            volume = self._value(candle, "volume")
            average_volume = sum(volumes, Decimal("0")) / len(volumes) if volumes else None
            volume_ratio = float(Decimal(str(volume)) / average_volume) if volume is not None and average_volume else None
            body_ratio = float(body / candle_range) if candle_range else 0.0
            displaced = atr_ratio is not None and atr_ratio >= self.minimum_atr_ratio and body_ratio >= self.minimum_body_ratio
            output.append(DisplacementFeature(
                candle_close_time(candle), str(self._value(candle, "symbol")), str(self._value(candle, "timeframe")),
                body, candle_range, round(atr_ratio, 4) if atr_ratio is not None else None,
                "BULLISH" if close > open_ else "BEARISH" if close < open_ else "NEUTRAL",
                round(volume_ratio, 4) if volume_ratio is not None else None, displaced,
            ))
        return output


class RejectionDetector:
    def __init__(self, *, minimum_wick_ratio: float = 0.5):
        self.minimum_wick_ratio = minimum_wick_ratio

    def detect(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> list[RejectionFeature]:
        visible = closed_candle_prefix(candles, as_of_index=as_of_index)
        output = []
        for candle in visible:
            value = lambda name: candle[name] if isinstance(candle, dict) else getattr(candle, name)
            open_, high, low, close = (Decimal(str(value(name))) for name in ("open", "high", "low", "close"))
            candle_range = high - low
            upper = high - max(open_, close)
            lower = min(open_, close) - low
            direction = "BEARISH" if upper > lower else "BULLISH"
            ratio = float(max(upper, lower) / candle_range) if candle_range else 0.0
            output.append(RejectionFeature(
                candle_close_time(candle), str(value("symbol")), str(value("timeframe")),
                direction, round(ratio, 4), ratio >= self.minimum_wick_ratio,
            ))
        return output


class OrderBlockDetector:
    """Last opposite candle before an ATR displacement that breaks a rolling extreme."""

    def __init__(self, *, lookback: int = 5, atr_period: int = 14, minimum_atr_ratio: float = 1.5):
        self.lookback = max(2, lookback)
        self.displacement = DisplacementDetector(atr_period=atr_period, minimum_atr_ratio=minimum_atr_ratio)

    @staticmethod
    def _value(candle: Any, name: str) -> Any:
        return candle[name] if isinstance(candle, dict) else getattr(candle, name)

    def detect(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> list[OrderBlock]:
        visible = closed_candle_prefix(candles, as_of_index=as_of_index)
        displacements = self.displacement.detect(visible)
        output = []
        for index in range(1, len(visible)):
            feature = displacements[index]
            if not feature.displaced or feature.direction == "NEUTRAL":
                continue
            window = visible[max(0, index - self.lookback):index]
            close = Decimal(str(self._value(visible[index], "close")))
            broken = (
                close > max(Decimal(str(self._value(row, "high"))) for row in window)
                if feature.direction == "BULLISH" else
                close < min(Decimal(str(self._value(row, "low"))) for row in window)
            )
            if not broken:
                continue
            opposite = [
                row for row in window
                if (Decimal(str(self._value(row, "close"))) < Decimal(str(self._value(row, "open")))) == (feature.direction == "BULLISH")
            ]
            if not opposite:
                continue
            source = opposite[-1]
            zone_high = Decimal(str(self._value(source, "high")))
            zone_low = Decimal(str(self._value(source, "low")))
            later = visible[index + 1:]
            mitigated = any(
                Decimal(str(self._value(row, "low"))) <= zone_high and Decimal(str(self._value(row, "high"))) >= zone_low
                for row in later
            )
            broken_through = any(
                Decimal(str(self._value(row, "close"))) < zone_low if feature.direction == "BULLISH"
                else Decimal(str(self._value(row, "close"))) > zone_high
                for row in later
            )
            output.append(OrderBlock(
                feature.timestamp, self._value(source, "timestamp"), str(self._value(source, "symbol")),
                str(self._value(source, "timeframe")), feature.direction, zone_high, zone_low,
                round(min(100.0, (feature.atr_ratio or 0.0) * 35.0), 2), mitigated,
                "BREAKER_BLOCK" if mitigated and broken_through else "ORDER_BLOCK",
            ))
        return output
