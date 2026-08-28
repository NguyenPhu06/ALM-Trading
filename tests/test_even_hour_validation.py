"""Even-hour checkpoint validation (section 13).

Two jobs: record what every checkpoint saw, and ask whether those decisions
improved outcomes. The spec says "Do not assume they do", and the default verdict
here is NOT_PROVEN.
"""
from datetime import datetime, timedelta, timezone

import pytest

from validation.even_hour import (
    REQUIRED_OBSERVATIONS, CheckpointRecord, EvenHourValidator, EvenHourVerdict,
)

MOMENT = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)


def record(index=0, *, decision="EXIT", alignment="WITH_TREND", **overrides):
    payload = dict(
        checkpoint_id=f"cp-{index}", symbol="EURUSD", timestamp=MOMENT, decision=decision,
        reason="CONDITIONS_STILL_VALID", trend="BULL", liquidity="VALID", structure="VALID",
        ichimoku="ABOVE_CLOUD", rsi=55.0, adx=27.0, nn=0.72, strategy="CHAMPION",
        risk="ALLOWED", position_state="OPEN", alignment=alignment,
        required_confidence=0.45, confidence=0.7)
    payload.update(overrides)
    return CheckpointRecord(**payload)


def validator(**kwargs):
    kwargs.setdefault("minimum_samples", 10)
    kwargs.setdefault("minimum_effect", 0.0001)
    return EvenHourValidator(**kwargs)


def scored(count, *, improvement, decision="EXIT", alignment="WITH_TREND"):
    live = validator()
    for index in range(count):
        live.record(record(index, decision=decision, alignment=alignment))
        live.score(f"cp-{index}", realized_pnl=improvement, counterfactual_pnl=0.0)
    return live


# ------------------------------------------------------------- the recording
def test_a_checkpoint_records_every_declared_observation():
    """Section 13, field for field."""
    payload = record().as_dict()
    for name in REQUIRED_OBSERVATIONS:
        assert name in payload
    assert "decision" in payload and "reason" in payload


def test_a_complete_checkpoint_reports_itself_complete():
    assert record().complete is True and record().missing == ()


def test_a_checkpoint_missing_an_observation_is_incomplete():
    incomplete = record(adx=None, ichimoku=None)
    assert incomplete.complete is False
    assert set(incomplete.missing) == {"adx", "ichimoku"}


def test_a_checkpoint_can_be_built_from_an_exit_verdict():
    """The validation asks about the same evidence the decision used."""
    from execution.demo.exit_engine import DemoExitEngine
    from observation.regime import MarketRegime

    verdict = DemoExitEngine().decide(
        direction="BUY", entry_time=MOMENT - timedelta(hours=1), current_price=1.1020,
        regime=MarketRegime.BULL, now=MOMENT, stop_loss=1.0950, take_profit=1.1100,
        strategy_confidence=0.8, nn_confidence=0.8)
    live = validator()
    built = live.from_verdict(verdict, checkpoint_id="cp-1", symbol="EURUSD",
                              observations={"ichimoku": "ABOVE_CLOUD", "rsi": 55.0,
                                            "adx": 27.0, "strategy": "CHAMPION"},
                              position_state="OPEN")
    assert built.decision == "HOLD"
    assert built.trend == str(MarketRegime.BULL)
    assert built.alignment == "WITH_TREND"
    assert built.complete is True


# ------------------------------------------------------------- the improvement
def test_an_unscored_checkpoint_has_no_improvement():
    assert record().improvement is None


def test_scoring_attaches_the_counterfactual():
    live = validator()
    live.record(record())
    scored_record = live.score("cp-0", realized_pnl=1.0, counterfactual_pnl=0.4)
    assert scored_record.improvement == pytest.approx(0.6)


def test_scoring_an_unknown_checkpoint_returns_nothing():
    assert validator().score("nope", realized_pnl=1.0, counterfactual_pnl=0.0) is None


# ---------------------------------------------------------------- the verdict
def test_the_default_verdict_on_no_evidence_is_insufficient_data():
    report = validator().evaluate()
    assert report.verdict is EvenHourVerdict.INSUFFICIENT_DATA
    assert "INSUFFICIENT_SAMPLES" in report.reasons


def test_a_small_sample_is_insufficient_data():
    report = scored(3, improvement=1.0).evaluate()
    assert report.verdict is EvenHourVerdict.INSUFFICIENT_DATA


def test_a_positive_effect_inside_the_noise_floor_is_not_proven():
    """Do not assume checkpoints help: a tiny positive is still not evidence."""
    report = scored(20, improvement=0.00001).evaluate()
    assert report.verdict is EvenHourVerdict.NOT_PROVEN
    assert "EFFECT_BELOW_MINIMUM" in report.reasons


def test_a_clear_improvement_is_reported_as_improving():
    report = scored(20, improvement=1.0).evaluate()
    assert report.verdict is EvenHourVerdict.IMPROVES
    assert report.mean_improvement == pytest.approx(1.0)


def test_checkpoints_that_cost_money_are_harmful():
    report = scored(20, improvement=-1.0).evaluate()
    assert report.verdict is EvenHourVerdict.HARMFUL
    assert "CHECKPOINTS_COST_MORE_THAN_THEY_SAVED" in report.reasons


def test_exits_and_holds_are_scored_separately():
    live = validator()
    for index in range(10):
        live.record(record(index, decision="EXIT"))
        live.score(f"cp-{index}", realized_pnl=1.0, counterfactual_pnl=0.0)
    for index in range(10, 20):
        live.record(record(index, decision="HOLD"))
        live.score(f"cp-{index}", realized_pnl=0.0, counterfactual_pnl=1.0)
    report = live.evaluate()
    assert report.exits == 10 and report.holds == 10
    assert report.exit_improvement == pytest.approx(1.0)
    assert report.hold_improvement == pytest.approx(-1.0)


def test_counter_trend_checkpoints_are_reported_separately():
    report = scored(20, improvement=1.0, alignment="COUNTER_TREND").evaluate()
    assert report.counter_trend_checkpoints == 20
    assert report.counter_trend_improvement == pytest.approx(1.0)


def test_incomplete_observations_are_flagged_in_the_verdict():
    live = validator()
    for index in range(20):
        live.record(record(index, adx=None))
        live.score(f"cp-{index}", realized_pnl=1.0, counterfactual_pnl=0.0)
    report = live.evaluate()
    assert "INCOMPLETE_CHECKPOINT_OBSERVATIONS" in report.reasons


def test_the_report_states_that_the_policy_is_a_hypothesis():
    assert "hypothesis" in validator().evaluate().as_dict()["note"]


def test_unscored_checkpoints_are_counted_but_not_scored():
    live = validator()
    for index in range(20):
        live.record(record(index))
    report = live.evaluate()
    assert report.checkpoints == 20 and report.scored == 0
    assert report.verdict is EvenHourVerdict.INSUFFICIENT_DATA
