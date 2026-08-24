from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import pstdev
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
    plus_di: float | None = None
    minus_di: float | None = None
    ichimoku_chikou: float | None = None
    price_above_cloud: bool | None = None
    price_below_cloud: bool | None = None
    cloud_bullish: bool | None = None
    cloud_bearish: bool | None = None
    tenkan_kijun_cross: str | None = None
    cloud_breakout: str | None = None
    rsi_overbought: bool | None = None
    rsi_oversold: bool | None = None
    rsi_midline: str | None = None
    rsi_slope: float | None = None
    rsi_recovery: bool | None = None
    rsi_divergence: str | None = None
    is_possible_exhaustion: bool | None = None
    trend_strength: str | None = None
    trend_direction: str | None = None
    adx_rising: bool | None = None
    adx_falling: bool | None = None
    atr_percentage: float | None = None
    rolling_volatility: float | None = None
    range_percentile: float | None = None
    volatility_state: str | None = None
    calculation_version: str = "phase3.v1"
    timestamp: datetime | None = None
    symbol: str | None = None


class MTFIndicatorEngine:
    """Calculate each timeframe independently; values are never mixed across bars."""

    def __init__(
        self, *, rsi_period: int = 14, adx_period: int = 14, atr_period: int = 14,
        tenkan_period: int = 9, kijun_period: int = 26, senkou_b_period: int = 52,
        ichimoku_displacement: int = 26, rsi_overbought: float = 70,
        rsi_oversold: float = 30, volatility_period: int = 20,
    ):
        self.rsi_period = rsi_period
        self.adx_period = adx_period
        self.atr_period = atr_period
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_b_period = senkou_b_period
        self.ichimoku_displacement = ichimoku_displacement
        self.rsi_overbought = rsi_overbought
        self.rsi_oversold = rsi_oversold
        self.volatility_period = volatility_period

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
        adx, plus_di, minus_di = self._adx_bundle(highs, lows, closes, self.adx_period)
        previous_adx = self._adx(highs[:-1], lows[:-1], closes[:-1], self.adx_period)
        tenkan = self._midpoint(highs, lows, self.tenkan_period)
        kijun = self._midpoint(highs, lows, self.kijun_period)
        cloud_index = max(0, len(closes) - self.ichimoku_displacement)
        cloud_highs, cloud_lows = highs[:cloud_index], lows[:cloud_index]
        cloud_tenkan = self._midpoint(cloud_highs, cloud_lows, self.tenkan_period)
        cloud_kijun = self._midpoint(cloud_highs, cloud_lows, self.kijun_period)
        visible_senkou_b = self._midpoint(cloud_highs, cloud_lows, self.senkou_b_period)
        visible_senkou_a = (cloud_tenkan + cloud_kijun) / 2 if cloud_tenkan is not None and cloud_kijun is not None else None
        senkou_b = self._midpoint(highs, lows, self.senkou_b_period)
        senkou_a = (tenkan + kijun) / 2 if tenkan is not None and kijun is not None else None
        available = all(value is not None for value in (rsi, adx, atr, tenkan, kijun, senkou_a, senkou_b))
        reason = None if available else "INSUFFICIENT_HISTORY"
        previous_rsi = self._rsi(closes[:-1], self.rsi_period)
        rsi_slope = rsi - previous_rsi if rsi is not None and previous_rsi is not None else None
        cloud_top = max(visible_senkou_a, visible_senkou_b) if visible_senkou_a is not None and visible_senkou_b is not None else None
        cloud_bottom = min(visible_senkou_a, visible_senkou_b) if visible_senkou_a is not None and visible_senkou_b is not None else None
        above = closes[-1] > cloud_top if cloud_top is not None else None
        below = closes[-1] < cloud_bottom if cloud_bottom is not None else None
        previous_tenkan = self._midpoint(highs[:-1], lows[:-1], self.tenkan_period)
        previous_kijun = self._midpoint(highs[:-1], lows[:-1], self.kijun_period)
        cross = None
        if None not in (tenkan, kijun, previous_tenkan, previous_kijun):
            if previous_tenkan <= previous_kijun and tenkan > kijun:
                cross = "BULLISH"
            elif previous_tenkan >= previous_kijun and tenkan < kijun:
                cross = "BEARISH"
        breakout = None
        if len(closes) > 1 and cloud_top is not None and cloud_bottom is not None:
            if closes[-2] <= cloud_top < closes[-1]:
                breakout = "BULLISH"
            elif closes[-2] >= cloud_bottom > closes[-1]:
                breakout = "BEARISH"
        atr_pct = atr / closes[-1] * 100 if atr and closes[-1] else None
        rolling_volatility = self._rolling_volatility(closes, self.volatility_period)
        range_percentile = self._range_percentile(highs, lows, 50)
        volatility_state = self._volatility_state(range_percentile)
        trend_strength = self._trend_strength(adx)
        trend_direction = "BULLISH" if plus_di is not None and minus_di is not None and plus_di > minus_di else "BEARISH" if plus_di is not None and minus_di is not None and minus_di > plus_di else "NEUTRAL"
        divergence = self._rsi_divergence(closes, self.rsi_period)
        return IndicatorSnapshot(
            timeframe, candle_close_time(visible[-1]), available,
            self._round(rsi), self._round(adx), self._round(atr, 8),
            self._round(tenkan, 8), self._round(kijun, 8),
            self._round(senkou_a, 8), self._round(senkou_b, 8), reason,
            self._round(plus_di), self._round(minus_di), self._round(closes[-1], 8),
            above, below,
            visible_senkou_a > visible_senkou_b if visible_senkou_a is not None and visible_senkou_b is not None else None,
            visible_senkou_a < visible_senkou_b if visible_senkou_a is not None and visible_senkou_b is not None else None,
            cross, breakout,
            rsi >= self.rsi_overbought if rsi is not None else None,
            rsi <= self.rsi_oversold if rsi is not None else None,
            "ABOVE" if rsi is not None and rsi > 50 else "BELOW" if rsi is not None and rsi < 50 else "AT",
            self._round(rsi_slope),
            previous_rsi is not None and rsi is not None and previous_rsi <= self.rsi_oversold < rsi,
            divergence,
            bool(rsi is not None and rsi_slope is not None and ((rsi >= self.rsi_overbought and rsi_slope < 0) or (rsi <= self.rsi_oversold and rsi_slope > 0))),
            trend_strength, trend_direction,
            adx is not None and previous_adx is not None and adx > previous_adx,
            adx is not None and previous_adx is not None and adx < previous_adx,
            self._round(atr_pct), self._round(rolling_volatility, 8),
            self._round(range_percentile, 2), volatility_state,
            "phase3.v1", candle_close_time(visible[-1]), str(candle_value(visible[-1], "symbol", "")),
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
        return cls._adx_bundle(highs, lows, closes, period)[0]

    @classmethod
    def _adx_bundle(
        cls, highs: Sequence[float], lows: Sequence[float], closes: Sequence[float], period: int,
    ) -> tuple[float | None, float | None, float | None]:
        if len(closes) < period * 2 + 1:
            return None, None, None
        ranges = cls._true_ranges(highs, lows, closes)
        plus_dm = []
        minus_dm = []
        for index in range(1, len(closes)):
            up = highs[index] - highs[index - 1]
            down = lows[index - 1] - lows[index]
            plus_dm.append(up if up > down and up > 0 else 0.0)
            minus_dm.append(down if down > up and down > 0 else 0.0)
        dx_values = []
        latest_plus = latest_minus = None
        for end in range(period, len(ranges) + 1):
            atr_sum = sum(ranges[end - period:end])
            if atr_sum == 0:
                dx_values.append(0.0)
                continue
            plus_di = 100.0 * sum(plus_dm[end - period:end]) / atr_sum
            minus_di = 100.0 * sum(minus_dm[end - period:end]) / atr_sum
            latest_plus, latest_minus = plus_di, minus_di
            denominator = plus_di + minus_di
            dx_values.append(0.0 if denominator == 0 else 100.0 * abs(plus_di - minus_di) / denominator)
        adx = sum(dx_values[-period:]) / period if len(dx_values) >= period else None
        return adx, latest_plus, latest_minus

    @staticmethod
    def _midpoint(highs: Sequence[float], lows: Sequence[float], period: int) -> float | None:
        if len(highs) < period:
            return None
        return (max(highs[-period:]) + min(lows[-period:])) / 2.0

    @staticmethod
    def _trend_strength(adx: float | None) -> str | None:
        if adx is None:
            return None
        if adx < 15:
            return "NO_TREND"
        if adx < 25:
            return "WEAK_TREND"
        if adx < 40:
            return "MODERATE_TREND"
        return "STRONG_TREND"

    @staticmethod
    def _rolling_volatility(closes: Sequence[float], period: int) -> float | None:
        if len(closes) < period + 1:
            return None
        returns = [(current / previous) - 1.0 for previous, current in zip(closes[-period - 1:-1], closes[-period:]) if previous]
        return pstdev(returns) if len(returns) >= 2 else None

    @staticmethod
    def _range_percentile(highs: Sequence[float], lows: Sequence[float], period: int) -> float | None:
        ranges = [high - low for high, low in zip(highs[-period:], lows[-period:])]
        if len(ranges) < 2:
            return None
        return 100.0 * sum(item <= ranges[-1] for item in ranges) / len(ranges)

    @staticmethod
    def _volatility_state(percentile: float | None) -> str | None:
        if percentile is None:
            return None
        if percentile <= 20:
            return "LOW_VOLATILITY"
        if percentile <= 70:
            return "NORMAL_VOLATILITY"
        if percentile <= 90:
            return "HIGH_VOLATILITY"
        return "EXTREME_VOLATILITY"

    @classmethod
    def _rsi_divergence(cls, closes: Sequence[float], period: int, lookback: int = 5) -> str | None:
        if len(closes) < period + lookback + 1:
            return None
        current = cls._rsi(closes, period)
        previous = cls._rsi(closes[:-lookback], period)
        if current is None or previous is None:
            return None
        if closes[-1] < closes[-lookback - 1] and current > previous:
            return "BULLISH"
        if closes[-1] > closes[-lookback - 1] and current < previous:
            return "BEARISH"
        return None
