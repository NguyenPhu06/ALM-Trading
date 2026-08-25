"""Backtesting namespace."""
from backtest.data_loader import BacktestDataLoader
from backtest.contracts import EvaluationAction, SimulatedTrade, SimulationRiskLimits, SnapshotStrategy, StrategyDecision, TradeDirection
from backtest.dca import DCAConfig, DCASimulator, SimulatedPosition
from backtest.time_exit import TimeBasedExitEngine, TimeExitEvaluation

__all__ = [
    "BacktestDataLoader", "DCAConfig", "DCASimulator", "EvaluationAction",
    "SimulatedPosition", "SimulatedTrade", "SimulationRiskLimits", "SnapshotStrategy", "StrategyDecision",
    "TimeBasedExitEngine", "TimeExitEvaluation", "TradeDirection",
]
from backtest.strategy_analysis import ablation_test, randomized_control, walk_forward_folds
from backtest.strategy_engine import (
    BacktestTrade, PerformanceMetrics, StrategyBacktestEngine, StrategyBacktestEvent,
    TransactionCosts, performance_metrics, regime_performance,
)

__all__ = ["BacktestTrade", "PerformanceMetrics", "StrategyBacktestEngine",
           "StrategyBacktestEvent", "TransactionCosts", "ablation_test",
           "performance_metrics", "randomized_control", "regime_performance",
           "walk_forward_folds"]
