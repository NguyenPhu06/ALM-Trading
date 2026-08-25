from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backtest.contracts import EvaluationAction, TradeDirection
from backtest.dca import DCASimulator, SimulatedPosition
from features.intelligence import MarketStateSnapshot


@dataclass(frozen=True, slots=True)
class TimeExitEvaluation:
    timestamp: datetime
    action: EvaluationAction
    reason: str
    pnl: float
    drawdown: float
    context: dict[str, Any]


class TimeBasedExitEngine:
    def __init__(self, *, maximum_holding_time: timedelta = timedelta(hours=8), reduce_drawdown: float = 0.01):
        self.maximum_holding_time = maximum_holding_time
        self.reduce_drawdown = reduce_drawdown

    def evaluate(
        self, position: SimulatedPosition, snapshot: MarketStateSnapshot, *,
        timestamp: datetime, current_price: float,
    ) -> TimeExitEvaluation:
        simulator = DCASimulator()
        pnl = simulator.pnl(position, current_price)
        drawdown = simulator.drawdown_fraction(position, current_price)
        htf = snapshot.market_regime.get("higher_timeframe_bias", "RANGING")
        invalidated = (position.direction is TradeDirection.LONG and htf == "BEARISH") or (
            position.direction is TradeDirection.SHORT and htf == "BULLISH"
        )
        if invalidated:
            action, reason = EvaluationAction.INVALIDATE, "HIGHER_TIMEFRAME_TREND_INVALIDATION"
        elif timestamp - position.entry_time >= self.maximum_holding_time:
            action, reason = EvaluationAction.EXIT, "TIME_BASED_EXIT"
        elif drawdown >= self.reduce_drawdown or any(
            state.volatility.get("state") == "EXTREME_VOLATILITY" for state in snapshot.timeframes.values()
        ):
            action, reason = EvaluationAction.REDUCE, "DRAWDOWN_OR_EXTREME_VOLATILITY"
        else:
            action, reason = EvaluationAction.HOLD, "CONTEXT_REMAINS_VALID"
        m15 = snapshot.timeframes.get("M15")
        return TimeExitEvaluation(timestamp, action, reason, pnl, drawdown, {
            "trend": htf, "structure": m15.structure if m15 else None,
            "rsi": m15.indicators.get("rsi") if m15 else None,
            "adx": m15.indicators.get("adx") if m15 else None,
            "ichimoku_state": "ABOVE" if m15 and m15.indicators.get("price_above_cloud") else "BELOW" if m15 and m15.indicators.get("price_below_cloud") else "UNKNOWN",
            "liquidity": m15.liquidity if m15 else {},
            "volatility": m15.volatility if m15 else {},
        })
