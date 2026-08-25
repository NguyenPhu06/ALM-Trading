from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import pstdev
from typing import Any, Sequence

from features.candles import candle_close_time, candle_value, closed_candle_prefix


@dataclass(frozen=True, slots=True)
class ForwardMarketLabel:
    timestamp: datetime
    symbol: str
    timeframe: str
    horizon_bars: int
    label_end_timestamp: datetime
    future_return: float
    maximum_favorable_excursion: float
    maximum_adverse_excursion: float
    future_drawdown: float
    future_volatility: float
    label_version: str = "forward.v1"


class ForwardLabeler:
    """Offline target generation. Future candles are used only in returned labels."""

    def __init__(self, *, horizon_bars: int = 4):
        if horizon_bars < 1:
            raise ValueError("horizon_bars must be positive")
        self.horizon_bars = horizon_bars

    def generate(self, candles: Sequence[Any]) -> list[ForwardMarketLabel]:
        closed = closed_candle_prefix(candles)
        output = []
        for index in range(len(closed) - self.horizon_bars):
            current = closed[index]
            future = closed[index + 1:index + self.horizon_bars + 1]
            price = float(candle_value(current, "close"))
            future_closes = [float(candle_value(row, "close")) for row in future]
            future_highs = [float(candle_value(row, "high")) for row in future]
            future_lows = [float(candle_value(row, "low")) for row in future]
            step_returns = [
                current_close / previous_close - 1.0
                for previous_close, current_close in zip([price, *future_closes[:-1]], future_closes)
                if previous_close
            ]
            output.append(ForwardMarketLabel(
                candle_close_time(current), str(candle_value(current, "symbol")),
                str(candle_value(current, "timeframe")), self.horizon_bars,
                candle_close_time(future[-1]), future_closes[-1] / price - 1.0,
                max(future_highs) / price - 1.0, min(future_lows) / price - 1.0,
                min(close / price - 1.0 for close in future_closes),
                pstdev(step_returns) if len(step_returns) >= 2 else 0.0,
            ))
        return output


@dataclass(frozen=True, slots=True)
class MultiHorizonLabel:
    timestamp: datetime
    symbol: str
    timeframe: str
    label_end_timestamp: datetime
    future_return_1: float
    future_return_3: float
    future_return_5: float
    future_return_10: float
    maximum_favorable_excursion: float
    maximum_adverse_excursion: float
    classification: str
    long_outcome: str
    short_outcome: str
    label_version: str = "phase4.labels.v1"


class MultiHorizonLabeler:
    """Generate offline targets. No returned value is eligible for feature extraction."""

    HORIZONS = (1, 3, 5, 10)

    def __init__(self, *, classification_threshold: float, outcome_threshold: float | None = None):
        if classification_threshold <= 0:
            raise ValueError("classification_threshold must be positive")
        self.classification_threshold = float(classification_threshold)
        self.outcome_threshold = float(outcome_threshold or classification_threshold)

    def generate(self, candles: Sequence[Any]) -> list[MultiHorizonLabel]:
        closed = closed_candle_prefix(candles)
        maximum_horizon = max(self.HORIZONS)
        output: list[MultiHorizonLabel] = []
        for index in range(len(closed) - maximum_horizon):
            current = closed[index]
            future = closed[index + 1:index + maximum_horizon + 1]
            price = float(candle_value(current, "close"))
            returns = {
                horizon: float(candle_value(future[horizon - 1], "close")) / price - 1.0
                for horizon in self.HORIZONS
            }
            highs = [float(candle_value(row, "high")) / price - 1.0 for row in future]
            lows = [float(candle_value(row, "low")) / price - 1.0 for row in future]
            mfe, mae = max(highs), min(lows)
            primary = returns[5]
            classification = (
                "UP" if primary > self.classification_threshold else
                "DOWN" if primary < -self.classification_threshold else "NEUTRAL"
            )
            output.append(MultiHorizonLabel(
                candle_close_time(current), str(candle_value(current, "symbol")),
                str(candle_value(current, "timeframe")), candle_close_time(future[-1]),
                returns[1], returns[3], returns[5], returns[10], mfe, mae, classification,
                self._outcome(mfe, mae), self._outcome(-mae, -mfe),
            ))
        return output

    def _outcome(self, favorable: float, adverse: float) -> str:
        favorable_hit = favorable >= self.outcome_threshold
        adverse_hit = adverse <= -self.outcome_threshold
        if favorable_hit and adverse_hit:
            return "MIXED"
        if favorable_hit:
            return "FAVORABLE"
        if adverse_hit:
            return "ADVERSE"
        return "NEUTRAL"
