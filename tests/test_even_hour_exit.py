"""The even-hour exit policy (sections 21 and 22).

The rule this file protects: the clock changing is not a reason to be flat. At a
checkpoint the position is *re-evaluated* against the configured exit policy, and
a counter-trend position is held to a stricter confidence bar than a with-trend
one. Between checkpoints, only the conditions that do not wait for a clock apply.

Every exit carries a reason. There is no path here that closes a position without
naming why.
"""
from datetime import datetime, timedelta, timezone

import pytest

from execution.demo.exit_engine import DemoExitEngine, ExitAction, ExitReason
from observation.regime import MarketRegime
from observation.time_exit import TimeExitAnalyzer, TrendAlignment

CHECKPOINT = datetime(2026, 8, 27, 10, 0, tzinfo=timezone.utc)
BETWEEN = datetime(2026, 8, 27, 11, 17, tzinfo=timezone.utc)
ENTRY = datetime(2026, 8, 27, 9, 0, tzinfo=timezone.utc)


def engine(**kwargs):
    return DemoExitEngine(analyzer=TimeExitAnalyzer(
        checkpoint_hours=kwargs.pop("checkpoint_hours", 2),
        max_holding_hours=kwargs.pop("max_holding_hours", 8),
        counter_trend_min_confidence=kwargs.pop("counter_trend_min_confidence", 0.75),
        base_min_confidence=kwargs.pop("base_min_confidence", 0.45)))


def decide(**overrides):
    payload = dict(direction="BUY", entry_time=ENTRY, current_price=1.1020,
                   regime=MarketRegime.BULL, now=CHECKPOINT, stop_loss=1.0950,
                   take_profit=1.1100, strategy_confidence=0.80, nn_confidence=0.80)
    payload.update(overrides)
    return engine().decide(**payload)


# ------------------------------------------------------ the clock is not a reason
def test_a_checkpoint_alone_does_not_force_an_exit():
    """Section 22: do not blindly exit merely because the clock changed."""
    verdict = decide()
    assert verdict.at_checkpoint and verdict.action is ExitAction.HOLD
    assert verdict.reason is None


def test_between_checkpoints_the_decision_waits():
    verdict = decide(now=BETWEEN)
    assert verdict.action is ExitAction.WAIT
    assert not verdict.at_checkpoint
    assert "AWAITING_NEXT_CHECKPOINT" in verdict.reasons


def test_the_next_checkpoint_is_reported():
    verdict = decide(now=BETWEEN)
    assert verdict.next_checkpoint == datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------- counter-trend
def test_a_counter_trend_position_is_marked():
    verdict = decide(direction="BUY", regime=MarketRegime.BEAR)
    assert verdict.alignment == str(TrendAlignment.COUNTER_TREND)


def test_a_counter_trend_position_faces_a_stricter_bar():
    with_trend = decide(regime=MarketRegime.BULL)
    counter = decide(regime=MarketRegime.BEAR)
    assert counter.required_confidence > with_trend.required_confidence


def test_a_counter_trend_position_below_the_bar_exits_at_the_checkpoint():
    verdict = decide(regime=MarketRegime.BEAR, strategy_confidence=0.60, nn_confidence=0.60)
    assert verdict.action is ExitAction.EXIT
    assert verdict.reason is ExitReason.TIME_EXIT
    assert "COUNTER_TREND_STRICTER_BAR" in verdict.reasons


def test_the_same_confidence_is_fine_with_the_trend():
    verdict = decide(regime=MarketRegime.BULL, strategy_confidence=0.60, nn_confidence=0.60)
    assert verdict.action is ExitAction.HOLD


def test_a_range_regime_is_neutral():
    verdict = decide(regime=MarketRegime.RANGE)
    assert verdict.alignment == str(TrendAlignment.NEUTRAL)


# --------------------------------------------------- conditions that never wait
def test_a_stop_loss_hit_exits_between_checkpoints():
    verdict = decide(now=BETWEEN, current_price=1.0940)
    assert verdict.action is ExitAction.EXIT and verdict.reason is ExitReason.STOP_LOSS


def test_a_take_profit_hit_exits_between_checkpoints():
    verdict = decide(now=BETWEEN, current_price=1.1120)
    assert verdict.action is ExitAction.EXIT and verdict.reason is ExitReason.TAKE_PROFIT


def test_a_short_position_uses_the_other_side_of_its_stops():
    verdict = engine().decide(direction="SELL", entry_time=ENTRY, current_price=1.1060,
                              regime=MarketRegime.BEAR, now=BETWEEN, stop_loss=1.1050,
                              take_profit=1.0900, strategy_confidence=0.8, nn_confidence=0.8)
    assert verdict.reason is ExitReason.STOP_LOSS


def test_a_risk_block_is_an_emergency_exit():
    verdict = decide(now=BETWEEN, risk_allowed=False)
    assert verdict.action is ExitAction.EXIT
    assert verdict.reason is ExitReason.RISK_EMERGENCY_EXIT


def test_structure_invalidation_exits_between_checkpoints():
    verdict = decide(now=BETWEEN, structure_valid=False)
    assert verdict.reason is ExitReason.STRUCTURE_INVALIDATION


def test_a_strategy_exit_is_honoured():
    verdict = decide(now=BETWEEN, strategy_exit=True)
    assert verdict.reason is ExitReason.STRATEGY_EXIT


def test_a_manual_exit_outranks_everything():
    verdict = decide(now=BETWEEN, manual_exit=True, risk_allowed=False)
    assert verdict.reason is ExitReason.MANUAL_EXIT


def test_the_maximum_holding_time_forces_an_exit():
    late = ENTRY + timedelta(hours=9)
    verdict = decide(now=late, entry_time=ENTRY)
    assert verdict.action is ExitAction.EXIT and verdict.reason is ExitReason.TIME_EXIT


# ---------------------------------------------------- checkpoint-only conditions
def test_weakened_liquidity_is_weighed_at_the_checkpoint_not_before():
    """A single liquidity read is noisier than a structural break, so it waits."""
    waiting = decide(now=BETWEEN, liquidity_valid=False)
    assert waiting.action is ExitAction.WAIT

    at_checkpoint = decide(now=CHECKPOINT, liquidity_valid=False)
    assert at_checkpoint.action is ExitAction.EXIT
    assert at_checkpoint.reason is ExitReason.LIQUIDITY_INVALIDATION


def test_weakened_indicators_exit_at_the_checkpoint():
    verdict = decide(now=CHECKPOINT, indicator_valid=False)
    assert verdict.action is ExitAction.EXIT and verdict.reason is ExitReason.TIME_EXIT


# ------------------------------------------------------------- the vocabulary
def test_the_eight_declared_exit_reasons_exist():
    assert {str(reason) for reason in ExitReason} == {
        "STOP_LOSS", "TAKE_PROFIT", "TIME_EXIT", "STRATEGY_EXIT", "STRUCTURE_INVALIDATION",
        "LIQUIDITY_INVALIDATION", "RISK_EMERGENCY_EXIT", "MANUAL_EXIT"}


def test_every_exit_names_a_reason():
    exits = [decide(now=BETWEEN, current_price=1.0940),
             decide(now=BETWEEN, risk_allowed=False),
             decide(now=BETWEEN, structure_valid=False),
             decide(now=BETWEEN, strategy_exit=True),
             decide(regime=MarketRegime.BEAR, strategy_confidence=0.1, nn_confidence=0.1)]
    assert all(verdict.should_exit and verdict.reason is not None for verdict in exits)


def test_the_verdict_records_the_conditions_it_weighed():
    verdict = decide()
    assert set(verdict.conditions) >= {"structure_valid", "liquidity_valid", "indicator_valid",
                                       "risk_allowed", "regime", "price", "stop_loss",
                                       "take_profit", "holding_seconds"}
    assert verdict.as_dict()["analysis"] is not None
