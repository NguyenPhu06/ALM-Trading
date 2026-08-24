from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from features.candles import candle_close_time, candle_is_closed, candle_value


@dataclass(frozen=True, slots=True)
class IndicatorSnapshot:
    timeframe: str
    as_of: datetime | None
    available: bool
    rsi: float | None
    adx: float | None
    atr: float | None
    ichimoku_tenkan: float | None
    ichimoku_kijun: float | None
    ichimoku_senkou_a: float | None
    ichimoku_senkou_b: float | None
    missing_reason: str | None = None


class MTFIndicatorEngine:
    """Calculate each timeframe independently; values are never mixed across bars."""

    def __init__(self, *, rsi_period: int = 14, adx_period: int = 14, atr_period: int = 14):
        self.rsi_period = rsi_period
        self.adx_period = adx_period
        self.atr_period = atr_period

    def calculate_matrix(
        self,
        candles_by_timeframe: Mapping[str, Sequence[Any]],
        *,
        as_of: datetime | None = None,
        timeframes: Sequence[str] = ("D1", "H4", "H1", "M15", "M5", "M1"),
    ) -> dict[str, IndicatorSnapshot]:
        return {
            timeframe: self.calculate(candles_by_timeframe.get(timeframe, ()), timeframe, as_of=as_of)
            for timeframe in timeframes
        }

    def calculate(self, candles: Sequence[Any], timeframe: str, *, as_of: datetime | None = None) -> IndicatorSnapshot:
        visible = [
            candle for candle in candles
            if candle_is_closed(candle) and (as_of is None or candle_close_time(candle) <= as_of)
        ]
        visible.sort(key=lambda candle: candle_value(candle, "timestamp"))
        if not visible:
            return IndicatorSnapshot(timeframe, as_of, False, None, None, None, None, None, None, None, "NO_CLOSED_CANDLES")
        closes = [float(candle_value(candle, "close")) for candle in visible]
        highs = [float(candle_value(candle, "high")) for candle in visible]
        lows = [float(candle_value(candle, "low")) for candle in visible]
        rsi = self._rsi(closes, self.rsi_period)
        atr = self._atr(highs, lows, closes, self.atr_period)
        adx = self._adx(highs, lows, closes, self.adx_period)
        tenkan = self._midpoint(highs, lows, 9)
        kijun = self._midpoint(highs, lows, 26)
        senkou_b = self._midpoint(highs, lows, 52)
        senkou_a = (tenkan + kijun) / 2 if tenkan is not None and kijun is not None else None
        available = all(value is not None for value in (rsi, adx, atr, tenkan, kijun, senkou_a, senkou_b))
        reason = None if available else "INSUFFICIENT_HISTORY"
        return IndicatorSnapshot(
            timeframe, candle_close_time(visible[-1]), available,
            self._round(rsi), self._round(adx), self._round(atr, 8),
            self._round(tenkan, 8), self._round(kijun, 8),
            self._round(senkou_a, 8), self._round(senkou_b, 8), reason,
        )

    @staticmethod
    def _round(value: float | None, digits: int = 4) -> float | None:
        return None if value is None else round(value, digits)

    @staticmethod
    def _rsi(closes: Sequence[float], period: int) -> float | None:
        if len(closes) < period + 1:
            return None
        changes = [current - previous for previous, current in zip(closes, closes[1:])][-period:]
        gain = sum(max(change, 0.0) for change in changes) / period
        loss = sum(max(-change, 0.0) for change in changes) / period
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    @staticmethod
    def _true_ranges(highs: Sequence[float], lows: Sequence[float], closes: Sequence[float]) -> list[float]:
        return [
            max(highs[index] - lows[index], abs(highs[index] - closes[index - 1]), abs(lows[index] - closes[index - 1]))
            for index in range(1, len(closes))
        ]

    @classmethod
    def _atr(cls, highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> float | None:
        ranges = cls._true_ranges(highs, lows, closes)
        return sum(ranges[-period:]) / period if len(ranges) >= period else None

    @classmethod
    def _adx(cls, highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int) -> float | None:
        if len(closes) < period * 2 + 1:
            return None
        ranges = cls._true_ranges(highs, lows, closes)
        plus_dm = []
        minus_dm = []
        for index in range(1, len(closes)):
            up = highs[index] - highs[index - 1]
            down = lows[index - 1] - lows[index]
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
        dx_values = []
        for end in range(period, len(ranges) + 1):
            atr_sum = sum(ranges[end - period:end])
            if atr_sum == 0:
                dx_values.append(0.0)
                continue
            plus_di = 100.0 * sum(plus_dm[end - period:end]) / atr_sum
            minus_di = 100.0 * sum(minus_dm[end - period:end]) / atr_sum
            denominator = plus_di + minus_di
            dx_values.append(0.0 if denominator == 0 else 100.0 * abs(plus_di - minus_di) / denominator)
        return sum(dx_values[-period:]) / period if len(dx_values) >= period else None

    @staticmethod
    def _midpoint(highs: Sequence[float], lows: Sequence[float], period: int) -> float | None:
        if len(highs) < period:
            return None
        return (max(highs[-period:]) + min(lows[-period:])) / 2.0
