from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Sequence

from features.candles import candle_close_time, closed_candle_prefix
from features.indicators import MTFIndicatorEngine


@dataclass(frozen=True, slots=True)
class VolatilitySnapshot:
    timestamp: datetime
    symbol: str
    timeframe: str
    atr: float | None
    atr_percentage: float | None
    rolling_volatility: float | None
    range_percentile: float | None
    state: str | None
    calculation_version: str = "phase3.v1"


class VolatilityEngine:
    def __init__(self, *, atr_period: int = 14, rolling_period: int = 20):
        self.indicators = MTFIndicatorEngine(atr_period=atr_period, volatility_period=rolling_period)

    def calculate(self, candles: Sequence[Any], *, as_of_index: int | None = None) -> VolatilitySnapshot | None:
        visible = closed_candle_prefix(candles, as_of_index=as_of_index)
        if not visible:
            return None
        value = lambda row, name: row[name] if isinstance(row, dict) else getattr(row, name)
        timeframe = str(value(visible[-1], "timeframe"))
        indicator = self.indicators.calculate(visible, timeframe, as_of=candle_close_time(visible[-1]))
        return VolatilitySnapshot(
            candle_close_time(visible[-1]), str(value(visible[-1], "symbol")), timeframe,
            indicator.atr, indicator.atr_percentage, indicator.rolling_volatility,
            indicator.range_percentile, indicator.volatility_state,
        )
