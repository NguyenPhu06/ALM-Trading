from datetime import timedelta
from backtest import StrategyBacktestEngine, StrategyBacktestEvent, TransactionCosts, randomized_control
from tests.phase6_helpers import NOW

def test_net_pnl_includes_costs_and_control_is_reproducible():
    events = [StrategyBacktestEvent(NOW, 1., "SIMULATE", "LONG"), StrategyBacktestEvent(NOW+timedelta(hours=1), 1.01, "EXIT")]
    trades, metrics = StrategyBacktestEngine().run(events, TransactionCosts(.001, .001, .001))
    assert trades[0].net_pnl < trades[0].gross_pnl
    assert metrics.total_trades == 1
    assert randomized_control(events, seed=3) == randomized_control(events, seed=3)

