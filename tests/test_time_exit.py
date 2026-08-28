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


# --------------------------------------- Phase 12: even-hour checkpoint model
# The Phase 6 tests above cover the paper TimeExitEngine. These cover the
# Phase 12 analysis model, which never closes anything.

def _analyzer(**kwargs):
    from observation.time_exit import TimeExitAnalyzer

    return TimeExitAnalyzer(**kwargs)


def _moment(hour, minute=0):
    from datetime import datetime, timezone

    return datetime(2026, 8, 27, hour, minute, tzinfo=timezone.utc)


def test_phase12_next_checkpoint_is_the_next_even_hour():
    analyzer = _analyzer(checkpoint_hours=2)
    assert analyzer.next_checkpoint(_moment(9, 15)) == _moment(10)
    assert analyzer.next_checkpoint(_moment(10, 30)) == _moment(12)


def test_phase12_between_checkpoints_the_decision_is_wait():
    from observation.time_exit import ExitDecision

    result = _analyzer().analyse(direction="BUY", regime="BULL", entry_time=_moment(9),
                                 now=_moment(9, 30), strategy_confidence=0.9,
                                 nn_confidence=0.9)
    assert result.decision is ExitDecision.WAIT
    assert "AWAITING_NEXT_CHECKPOINT" in result.reasons


def test_phase12_at_a_checkpoint_a_healthy_position_holds():
    from observation.time_exit import ExitDecision

    result = _analyzer().analyse(direction="BUY", regime="BULL", entry_time=_moment(9),
                                 now=_moment(10), strategy_confidence=0.9, nn_confidence=0.9)
    assert result.decision is ExitDecision.HOLD and result.at_checkpoint


def test_phase12_counter_trend_is_detected_and_held_to_a_stricter_bar():
    from observation.time_exit import ExitDecision, TrendAlignment

    result = _analyzer().analyse(direction="SELL", regime="STRONG_BULL",
                                 entry_time=_moment(9), now=_moment(10),
                                 strategy_confidence=0.60, nn_confidence=0.60)
    assert result.alignment is TrendAlignment.COUNTER_TREND
    assert result.required_confidence > 0.6
    assert result.decision is ExitDecision.EXIT
    assert "COUNTER_TREND_STRICTER_BAR" in result.reasons


def test_phase12_the_same_confidence_holds_when_it_is_with_trend():
    from observation.time_exit import ExitDecision, TrendAlignment

    result = _analyzer().analyse(direction="BUY", regime="STRONG_BULL",
                                 entry_time=_moment(9), now=_moment(10),
                                 strategy_confidence=0.60, nn_confidence=0.60)
    assert result.alignment is TrendAlignment.WITH_TREND
    assert result.decision is ExitDecision.HOLD


def test_phase12_a_range_regime_is_neutral_alignment():
    from observation.time_exit import TrendAlignment

    result = _analyzer().analyse(direction="BUY", regime="RANGE", entry_time=_moment(9),
                                 now=_moment(10), strategy_confidence=0.9, nn_confidence=0.9)
    assert result.alignment is TrendAlignment.NEUTRAL


def test_phase12_invalidated_structure_exits_regardless_of_the_clock():
    from observation.time_exit import ExitDecision

    result = _analyzer().analyse(direction="BUY", regime="BULL", entry_time=_moment(9),
                                 now=_moment(9, 17), strategy_confidence=0.9,
                                 nn_confidence=0.9, structure_valid=False)
    assert result.decision is ExitDecision.EXIT
    assert "STRUCTURE_INVALIDATED" in result.reasons


def test_phase12_a_blocked_risk_state_exits_regardless_of_the_clock():
    from observation.time_exit import ExitDecision

    result = _analyzer().analyse(direction="BUY", regime="BULL", entry_time=_moment(9),
                                 now=_moment(9, 17), strategy_confidence=0.9,
                                 nn_confidence=0.9, risk_allowed=False)
    assert result.decision is ExitDecision.EXIT and "RISK_BLOCKED" in result.reasons


def test_phase12_the_maximum_holding_time_forces_an_exit():
    from observation.time_exit import ExitDecision

    result = _analyzer(max_holding_hours=2).analyse(
        direction="BUY", regime="BULL", entry_time=_moment(1), now=_moment(9, 30),
        strategy_confidence=0.9, nn_confidence=0.9)
    assert result.decision is ExitDecision.EXIT
    assert "MAX_HOLDING_REACHED" in result.reasons


def test_phase12_weak_supporting_context_exits_at_a_checkpoint():
    from observation.time_exit import ExitDecision

    result = _analyzer().analyse(direction="BUY", regime="BULL", entry_time=_moment(9),
                                 now=_moment(10), strategy_confidence=0.9, nn_confidence=0.9,
                                 liquidity_valid=False)
    assert result.decision is ExitDecision.EXIT
    assert "SUPPORTING_CONTEXT_WEAKENED" in result.reasons


def test_phase12_the_analysis_never_closes_anything():
    result = _analyzer().analyse(direction="BUY", regime="BULL", entry_time=_moment(9),
                                 now=_moment(10), strategy_confidence=0.9, nn_confidence=0.9)
    assert result.executed is False
    assert result.as_dict()["executed"] is False
    from observation.time_exit import TimeExitAnalyzer

    for name in ("close", "close_position", "exit_position", "send"):
        assert not hasattr(TimeExitAnalyzer, name), name


def test_phase12_time_remaining_is_reported():
    result = _analyzer().analyse(direction="BUY", regime="BULL", entry_time=_moment(9),
                                 now=_moment(9, 30), strategy_confidence=0.9, nn_confidence=0.9)
    assert result.seconds_to_checkpoint == 1800
    assert result.holding_seconds == 1800
