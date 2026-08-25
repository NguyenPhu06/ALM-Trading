from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import sqrt
from statistics import mean, pstdev
from typing import Sequence


@dataclass(frozen=True, slots=True)
class StrategyBacktestEvent:
    timestamp: datetime
    price: float
    decision: str
    direction: str = "NONE"
    regime: str = "UNKNOWN"
    session: str = "OFF_SESSION"
    d1_bias: str = "NEUTRAL"
    h4_bias: str = "NEUTRAL"
    source_timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class TransactionCosts:
    spread: float = 0.0001
    commission: float = 0.0
    slippage: float = 0.00002


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    entry_time: datetime
    exit_time: datetime
    direction: str
    gross_pnl: float
    fees: float
    slippage: float
    net_pnl: float
    holding_minutes: float
    regime: str
    session: str
    d1_bias: str
    h4_bias: str
    dca_depth: int = 0
    time_exit: bool = False


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    total_trades: int
    win_rate: float
    loss_rate: float
    profit_factor: float | None
    expectancy: float
    average_win: float
    average_loss: float
    maximum_drawdown: float
    sharpe: float | None
    sortino: float | None
    average_holding_minutes: float
    dca_frequency: float
    maximum_dca_depth: int
    time_exit_frequency: float


class StrategyBacktestEngine:
    """Causal close-to-close simulation; events must already be known at their timestamp."""

    def run(self, events: Sequence[StrategyBacktestEvent], costs: TransactionCosts | None = None) -> tuple[list[BacktestTrade], PerformanceMetrics]:
        costs = costs or TransactionCosts()
        ordered = sorted(events, key=lambda event: event.timestamp)
        open_event: StrategyBacktestEvent | None = None
        trades: list[BacktestTrade] = []
        for event in ordered:
            if event.source_timestamp and event.source_timestamp > event.timestamp:
                raise ValueError("future-derived strategy event detected")
            if open_event is None and event.decision == "SIMULATE" and event.direction in {"LONG", "SHORT"}:
                open_event = event
            elif open_event is not None and event.decision in {"EXIT", "INVALIDATE"}:
                sign = 1 if open_event.direction == "LONG" else -1
                gross = sign * (event.price - open_event.price)
                fees = costs.spread + 2 * costs.commission
                slip = 2 * costs.slippage
                trades.append(BacktestTrade(open_event.timestamp, event.timestamp, open_event.direction,
                    gross, fees, slip, gross - fees - slip,
                    (event.timestamp - open_event.timestamp).total_seconds() / 60,
                    open_event.regime, open_event.session, open_event.d1_bias, open_event.h4_bias,
                    time_exit=event.decision == "EXIT"))
                open_event = None
        return trades, performance_metrics(trades)


def performance_metrics(trades: Sequence[BacktestTrade]) -> PerformanceMetrics:
    values = [trade.net_pnl for trade in trades]
    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    total = len(values)
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    equity = peak = drawdown = 0.
    for value in values:
        equity += value; peak = max(peak, equity); drawdown = max(drawdown, peak - equity)
    volatility = pstdev(values) if total > 1 else 0.
    downside = [value for value in values if value < 0]
    downside_dev = pstdev(downside) if len(downside) > 1 else 0.
    return PerformanceMetrics(
        total, len(wins) / total if total else 0., len(losses) / total if total else 0.,
        gross_profit / gross_loss if gross_loss else (None if not gross_profit else float("inf")),
        mean(values) if values else 0., mean(wins) if wins else 0., mean(losses) if losses else 0., drawdown,
        mean(values) / volatility * sqrt(total) if volatility else None,
        mean(values) / downside_dev * sqrt(total) if downside_dev else None,
        mean([trade.holding_minutes for trade in trades]) if trades else 0.,
        sum(trade.dca_depth > 0 for trade in trades) / total if total else 0.,
        max((trade.dca_depth for trade in trades), default=0),
        sum(trade.time_exit for trade in trades) / total if total else 0.,
    )


def regime_performance(trades: Sequence[BacktestTrade]) -> dict[str, dict[str, PerformanceMetrics]]:
    output: dict[str, dict[str, PerformanceMetrics]] = {}
    for field in ("regime", "session", "d1_bias", "h4_bias"):
        groups: dict[str, list[BacktestTrade]] = {}
        for trade in trades: groups.setdefault(str(getattr(trade, field)), []).append(trade)
        output[field] = {key: performance_metrics(rows) for key, rows in groups.items()}
    return output

