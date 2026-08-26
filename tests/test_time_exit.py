from datetime import timedelta
from strategy import ExitAction, TimeExitEngine, TradingSessionEngine
from tests.phase6_helpers import NOW

def test_time_exit_reassesses_instead_of_always_exiting():
    engine = TimeExitEngine(timezone_engine=TradingSessionEngine(timezone="UTC"))
    decision = engine.evaluate(entry_time=NOW-timedelta(hours=2), timestamp=NOW, structure_valid=True,
        regime_valid=True, risk_allowed=True, confidence=.8, drawdown=0.)
    assert decision.action is ExitAction.HOLD

def test_time_exit_invalidates_broken_structure():
    engine = TimeExitEngine(timezone_engine=TradingSessionEngine())
    assert engine.evaluate(entry_time=NOW, timestamp=NOW, structure_valid=False, regime_valid=True,
        risk_allowed=True, confidence=.8, drawdown=0.).action is ExitAction.INVALIDATE

def test_even_hour_checkpoint_can_hold_not_forced_exit():
    engine=TimeExitEngine(timezone_engine=TradingSessionEngine(timezone="UTC"))
    result=engine.evaluate(entry_time=NOW-timedelta(hours=1),timestamp=NOW,structure_valid=True,regime_valid=True,risk_allowed=True,confidence=.9,drawdown=0.)
    assert result.action is ExitAction.HOLD
