"""Champion / challenger, for models and for strategies.

Two parallel mechanisms with the same rule at the end of both: a challenger may
be *recommended* by evidence, but only a named human promotes it.

* Phase 13 — `ChampionChallengerComparator` scores a model on ten out-of-sample
  criteria.
* Phase 15 — `StrategyChallengerEvaluator` puts a strategy through five gates.
"""
import inspect

import pytest

from ai.model_registry.comparison import CRITERIA, ChampionChallengerComparator
from ai.model_registry.records import ModelState
from research.champion import (
    GATES,
    ChallengerVerdict,
    Gate,
    StrategyChallengerEvaluator,
    rejection_criteria,
)
from research.registry import ApprovalToken, StrategyStatus
from tests.phase13_helpers import model_record, weaker_record
from tests.phase15_helpers import registry_with, series, validated


def validated_record(model_id="m1", **overrides):
    """The comparator refuses an EXPERIMENTAL challenger by design."""
    return model_record(model_id, state=ModelState.VALIDATED, **overrides)


# ============================================================ Phase 13: models
def test_every_model_criterion_is_out_of_sample():
    """Training metrics count for nothing: no criterion may read them."""
    for name, (path, _) in CRITERIA.items():
        assert not path.startswith("training"), name
        assert path.split(".")[0] in {"test_metrics", "calibration",
                                      "walk_forward_metrics", "regime_metrics",
                                      "session_metrics"}, name


def test_there_are_ten_model_criteria():
    assert len(CRITERIA) == 10


def test_a_stronger_challenger_is_recommended():
    result = ChampionChallengerComparator().compare(
        champion=weaker_record("champion"), challenger=validated_record("challenger"))
    assert result.recommend_promotion
    assert result.challenger_wins >= 6


def test_a_weaker_challenger_is_not_recommended():
    result = ChampionChallengerComparator().compare(
        champion=model_record("champion"),
        challenger=weaker_record("challenger"))
    assert not result.recommend_promotion
    assert "CHAMPION_STILL_STRONGER" in result.reasons


def test_an_experimental_challenger_is_refused_outright():
    result = ChampionChallengerComparator().compare(
        champion=weaker_record("champion"),
        challenger=model_record("challenger", state=ModelState.EXPERIMENTAL))
    assert not result.recommend_promotion
    assert any("CHALLENGER_STATE" in reason for reason in result.reasons)


def test_a_challenger_without_an_edge_is_refused():
    result = ChampionChallengerComparator().compare(
        champion=weaker_record("champion"),
        challenger=validated_record("challenger", edge_verdict="NO_EDGE"))
    assert "CHALLENGER_HAS_NO_EDGE" in result.reasons


def test_a_challenger_that_does_not_beat_the_baselines_is_refused():
    result = ChampionChallengerComparator().compare(
        champion=weaker_record("champion"),
        challenger=validated_record("challenger",
                                    baseline_comparison={"beats_all_baselines": False}))
    assert "CHALLENGER_DOES_NOT_BEAT_BASELINES" in result.reasons


def test_too_few_wins_is_refused():
    """A challenger that wins some criteria but not enough of them."""
    mixed = validated_record(
        "challenger",
        test_metrics={"balanced_accuracy": 0.59, "log_loss": 0.95, "expectancy": 0.0004,
                      "max_drawdown": 0.05, "net_expectancy": 0.0003},
        calibration={"brier_score": 0.25},
        walk_forward_metrics={"mean_accuracy": 0.55, "stability": 0.70})
    result = ChampionChallengerComparator().compare(
        champion=model_record("champion"), challenger=mixed)
    assert not result.recommend_promotion
    assert 0 < result.challenger_wins < 6
    assert any("BELOW_6" in reason for reason in result.reasons)


def test_a_first_model_has_no_incumbent_to_beat():
    result = ChampionChallengerComparator().compare(
        champion=None, challenger=validated_record("first"))
    assert "NO_INCUMBENT_CHAMPION" in result.reasons
    assert result.recommend_promotion


def test_missing_metrics_are_incomparable_not_assumed_equal():
    result = ChampionChallengerComparator().compare(
        champion=model_record("champion", calibration={}, walk_forward_metrics={}),
        challenger=validated_record("challenger", calibration={},
                                    walk_forward_metrics={}))
    assert result.incomparable >= 3
    assert any(item.winner == "INCOMPARABLE" for item in result.criteria)


def test_every_criterion_is_reported_even_when_lost():
    result = ChampionChallengerComparator().compare(
        champion=model_record("champion"), challenger=weaker_record("challenger"))
    assert len(result.criteria) == len(CRITERIA)
    assert {item.name for item in result.criteria} == set(CRITERIA)


def test_the_model_comparator_recommends_but_never_promotes():
    """It may *mention* the approval token in its docstring; it may not call one."""
    source = inspect.getsource(ChampionChallengerComparator)
    assert ".promote(" not in source
    assert "ApprovalToken(" not in source
    assert "Recommends, never promotes" in source


def test_lower_is_better_criteria_are_scored_in_the_right_direction():
    """log loss and Brier must count downward, not upward."""
    for name in ("test_log_loss", "test_brier"):
        assert CRITERIA[name][1] is False


# ======================================================== Phase 15: strategies

def evaluator(**kwargs):
    kwargs.setdefault("minimum_samples", 100)
    return StrategyChallengerEvaluator(**kwargs)


def contest(*, champion_mean=0.0002, challenger_mean=0.0009, count=150,
            champion_windows=(0.55, 0.57, 0.56), challenger_windows=(0.60, 0.62, 0.61),
            **kwargs):
    return evaluator(**kwargs).evaluate(
        champion=series(count, mean=champion_mean, seed=1),
        challenger=series(count, mean=challenger_mean, seed=2, start=1000),
        champion_windows=list(champion_windows),
        challenger_windows=list(challenger_windows),
        champion_key="smc:v1", challenger_key="smc:v2")


# ------------------------------------------------------------- the five gates
def test_all_five_documented_gates_exist():
    assert [str(gate) for gate in GATES] == [
        "OUT_OF_SAMPLE", "WALK_FORWARD", "SAMPLE_SIZE", "RISK_ADJUSTED", "STABILITY"]


def test_every_gate_is_evaluated():
    report = contest()
    assert {gate.gate for gate in report.gates} == set(GATES)


def test_a_clearly_better_challenger_clears_every_gate():
    report = contest()
    assert report.failed_gates == ()
    assert report.verdict is ChallengerVerdict.RECOMMEND_PROMOTION


def test_a_missing_walk_forward_blocks_promotion():
    report = contest(challenger_windows=())
    assert Gate.WALK_FORWARD.value in report.failed_gates
    assert report.verdict is not ChallengerVerdict.RECOMMEND_PROMOTION


def test_an_inconsistent_walk_forward_blocks_promotion():
    report = contest(challenger_windows=(0.9, 0.05, 0.85))
    assert Gate.WALK_FORWARD.value in report.failed_gates


def test_too_few_samples_is_insufficient_evidence():
    report = contest(count=20)
    assert Gate.SAMPLE_SIZE.value in report.failed_gates
    assert report.verdict is ChallengerVerdict.INSUFFICIENT_EVIDENCE


def test_a_challenger_with_no_observations_fails_out_of_sample():
    report = evaluator().evaluate(champion=series(150), challenger=[],
                                  challenger_windows=[0.6, 0.6, 0.6])
    assert Gate.OUT_OF_SAMPLE.value in report.failed_gates


def test_a_worse_challenger_is_rejected():
    report = contest(champion_mean=0.0009, challenger_mean=0.0001)
    assert report.verdict is ChallengerVerdict.REJECT_CHALLENGER
    assert Gate.RISK_ADJUSTED.value in report.failed_gates


def test_an_indistinguishable_challenger_keeps_the_champion():
    report = contest(champion_mean=0.0004, challenger_mean=0.00041)
    assert report.verdict is ChallengerVerdict.KEEP_CHAMPION


def test_better_returns_with_worse_drawdown_do_not_pass_the_risk_gate():
    """Section 4's 'risk-adjusted': PnL alone is not the comparison."""
    champion = series(150, mean=0.0003, deviation=0.0002, seed=3)
    challenger = series(150, mean=0.0009, deviation=0.004, seed=4, start=1000)
    report = evaluator().evaluate(champion=champion, challenger=challenger,
                                  challenger_windows=[0.6, 0.62, 0.61])
    risk_gate = next(gate for gate in report.gates if gate.gate is Gate.RISK_ADJUSTED)
    assert risk_gate.data["challenger_drawdown"] > risk_gate.data["champion_drawdown"]
    assert not risk_gate.passed
    assert "DRAWDOWN_WORSE" in (risk_gate.detail or "")


def test_a_challenger_that_only_works_in_one_session_fails_stability():
    losing = series(60, mean=-0.0009, seed=6, start=2000, session="ASIA")
    winning = series(120, mean=0.0012, seed=7, start=3000, session="LONDON")
    report = evaluator().evaluate(champion=series(150, mean=0.0002, seed=8),
                                  challenger=winning + losing,
                                  challenger_windows=[0.6, 0.62, 0.61])
    stability = next(gate for gate in report.gates if gate.gate is Gate.STABILITY)
    assert not stability.passed
    assert "ASIA" in (stability.detail or "")


# --------------------------------------------------- a recommendation, not a promotion
def test_the_report_never_reports_itself_as_promoted():
    report = contest()
    assert report.promoted is False
    assert report.as_dict()["promoted"] is False
    assert report.as_dict()["requires_human_approval"] is True


def test_the_evaluator_cannot_promote():
    source = inspect.getsource(StrategyChallengerEvaluator)
    for token in ("promote", "ApprovalToken", "StrategyRegistry"):
        assert token not in source, token


def test_a_recommendation_still_needs_a_token_to_take_effect():
    registry = registry_with(
        __import__("research", fromlist=["strategy"]).strategy("smc", "candidate"))
    validated(registry, "smc:v1")
    report = contest()
    assert report.recommend_promotion

    # The recommendation changes nothing on its own.
    assert registry.get("smc:v1").status is StrategyStatus.VALIDATED
    registry.promote("smc:v1", ApprovalToken("nvphu", report.verdict))
    assert registry.get("smc:v1").status is StrategyStatus.CHAMPION


def test_the_report_carries_both_keys_and_the_deltas():
    report = contest()
    payload = report.as_dict()
    assert payload["champion_key"] == "smc:v1"
    assert payload["challenger_key"] == "smc:v2"
    assert payload["deltas"]["expectancy"] > 0


# --------------------------------------------------------- 10. rejection criteria
def test_the_rejection_criteria_are_stated():
    criteria = rejection_criteria()["criteria"]
    assert len(criteria) >= 6
    joined = " ".join(criteria).lower()
    for token in ("expectancy", "champion", "stability", "overconfident",
                  "multiple-testing", "holdout"):
        assert token in joined, token


def test_rejection_is_documented_as_terminal():
    assert "terminal" in rejection_criteria()["note"]
