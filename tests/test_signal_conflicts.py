"""Signal conflicts and weight research (sections 21 and 22)."""
import inspect

import pytest

from research.conflicts import (
    SIGNALS,
    ConflictEngine,
    ConflictType,
    Resolution,
    Severity,
    direction_of,
)
from research.weights import SignalWeightResearch
from tests.phase15_helpers import conflicting, observation, series


def engine():
    return ConflictEngine()


def with_signals(**overrides):
    return observation(1, signals=conflicting(**overrides))


# ------------------------------------------------------------ 21. detection
def test_the_documented_timeframe_conflict_is_detected():
    """D1/H4/H1 bullish while M15/M5 bearish."""
    row = with_signals(M15="BEAR", M5="BEAR", M30="BEAR")
    kinds = {conflict.conflict_type for conflict in engine().detect(row)}
    assert ConflictType.TIMEFRAME_CONFLICT in kinds


def test_agreement_across_timeframes_is_not_a_conflict():
    kinds = {conflict.conflict_type for conflict in engine().detect(with_signals())}
    assert ConflictType.TIMEFRAME_CONFLICT not in kinds


def test_the_documented_weak_trend_is_detected():
    """Ichimoku BULL, RSI NEUTRAL, ADX WEAK."""
    row = with_signals(rsi="NEUTRAL", adx="WEAK")
    conflicts = [c for c in engine().detect(row)
                 if c.conflict_type is ConflictType.WEAK_TREND]
    assert conflicts
    assert conflicts[0].resolution is Resolution.NO_TRADE


def test_the_documented_liquidity_versus_nn_conflict_is_detected():
    row = with_signals(liquidity="BULL", nn="BEAR")
    kinds = {conflict.conflict_type for conflict in engine().detect(row)}
    assert ConflictType.LIQUIDITY_NN_CONFLICT in kinds


def test_structure_versus_nn_is_detected():
    row = with_signals(market_structure="BULL", nn="BEAR")
    kinds = {conflict.conflict_type for conflict in engine().detect(row)}
    assert ConflictType.STRUCTURE_NN_CONFLICT in kinds


def test_disagreeing_indicators_are_detected():
    row = with_signals(ichimoku="BULL", rsi="BEAR", adx="BULL")
    kinds = {conflict.conflict_type for conflict in engine().detect(row)}
    assert ConflictType.INDICATOR_CONFLICT in kinds


def test_an_observation_without_signals_has_no_conflicts():
    assert engine().detect(observation(1, signals={})) == []


# --------------------------------------------------- severity and resolution
def test_a_full_timeframe_split_is_high_severity():
    row = with_signals(M15="BEAR", M5="BEAR", M30="BEAR")
    conflict = next(c for c in engine().detect(row)
                    if c.conflict_type is ConflictType.TIMEFRAME_CONFLICT)
    assert conflict.severity is Severity.HIGH


def test_the_resolution_records_which_side_was_taken():
    row = observation(1, predicted="UP", signals=conflicting(M15="BEAR", M5="BEAR",
                                                             M30="BEAR"))
    conflict = next(c for c in engine().detect(row)
                    if c.conflict_type is ConflictType.TIMEFRAME_CONFLICT)
    assert conflict.resolution is Resolution.FOLLOWED_HTF


def test_taking_the_lower_timeframe_side_is_recorded_as_such():
    row = observation(1, predicted="DOWN", signals=conflicting(M15="BEAR", M5="BEAR",
                                                               M30="BEAR"))
    conflict = next(c for c in engine().detect(row)
                    if c.conflict_type is ConflictType.TIMEFRAME_CONFLICT)
    assert conflict.resolution is Resolution.FOLLOWED_LTF


def test_no_trade_is_a_resolution():
    row = observation(1, predicted="WAIT", correct=None,
                      signals=conflicting(M15="BEAR", M5="BEAR", M30="BEAR"))
    conflict = next(c for c in engine().detect(row)
                    if c.conflict_type is ConflictType.TIMEFRAME_CONFLICT)
    assert conflict.resolution is Resolution.NO_TRADE


def test_the_outcome_is_recorded_with_the_conflict():
    row = observation(1, net=0.0009, predicted="UP",
                      signals=conflicting(liquidity="BULL", nn="BEAR"))
    conflict = next(c for c in engine().detect(row)
                    if c.conflict_type is ConflictType.LIQUIDITY_NN_CONFLICT)
    assert conflict.outcome_net_pnl == pytest.approx(0.0009)
    assert conflict.resolved_well is True


def test_a_losing_resolution_is_recorded_as_such():
    row = observation(1, net=-0.0009, correct=False, predicted="UP",
                      signals=conflicting(liquidity="BULL", nn="BEAR"))
    conflict = next(c for c in engine().detect(row)
                    if c.conflict_type is ConflictType.LIQUIDITY_NN_CONFLICT)
    assert conflict.resolved_well is False


# ----------------------------------------------------------------- the study
def test_the_study_counts_conflicted_and_clean_observations():
    conflicted = series(30, seed=1, signals=conflicting(M15="BEAR", M5="BEAR",
                                                        M30="BEAR"))
    clean = series(30, seed=2, start=1000, signals=conflicting())
    study = engine().study(conflicted + clean, minimum_samples=10)
    assert study["observations"] == 60
    assert study["conflicted_observations"] == 30


def test_the_study_compares_conflicted_against_clean_performance():
    conflicted = series(40, mean=-0.0008, seed=1,
                        signals=conflicting(M15="BEAR", M5="BEAR", M30="BEAR"))
    clean = series(40, mean=0.0008, seed=2, start=1000, signals=conflicting())
    study = engine().study(conflicted + clean, minimum_samples=10)
    assert study["conflicted_performance"]["expectancy"] < 0
    assert study["clean_performance"]["expectancy"] > 0


def test_the_study_groups_by_type_and_resolution():
    rows = series(30, seed=1, signals=conflicting(M15="BEAR", M5="BEAR", M30="BEAR"))
    study = engine().study(rows, minimum_samples=10)
    assert str(ConflictType.TIMEFRAME_CONFLICT) in study["by_type"]
    assert str(Resolution.FOLLOWED_HTF) in study["by_resolution"]


def test_the_study_states_it_changes_no_weight():
    study = engine().study(series(10, seed=1, signals=conflicting()), minimum_samples=5)
    assert "nothing here changes a signal weight" in study["note"]


# ------------------------------------------------------ 22. researched weights
def test_the_documented_signals_are_the_ones_researched():
    assert set(SIGNALS) == {"market_structure", "liquidity", "ichimoku", "rsi", "adx",
                            "nn", "mtf_regime"}


def test_a_signal_that_pays_when_followed_earns_a_weight():
    agreed = series(80, mean=0.0012, seed=1, predicted="UP",
                    signals={"liquidity": "BULL"})
    disagreed = series(80, mean=-0.0008, seed=2, start=1000, predicted="UP",
                       signals={"liquidity": "BEAR"})
    proposal = SignalWeightResearch(minimum_samples=50).run(agreed + disagreed)
    assert proposal.evidence["liquidity"].proposed_weight is not None
    assert "liquidity" in proposal.weighted


def test_a_signal_with_too_few_observations_gets_no_weight_not_a_small_one():
    rows = series(10, seed=1, predicted="UP", signals={"rsi": "BULL"})
    proposal = SignalWeightResearch(minimum_samples=50).run(rows)
    assert proposal.evidence["rsi"].proposed_weight is None
    assert "rsi" in proposal.unweighted


def test_a_signal_that_does_not_help_earns_no_weight():
    agreed = series(80, mean=-0.0008, seed=1, predicted="UP", signals={"adx": "BULL"})
    disagreed = series(80, mean=0.0012, seed=2, start=1000, predicted="UP",
                       signals={"adx": "BEAR"})
    proposal = SignalWeightResearch(minimum_samples=50).run(agreed + disagreed)
    assert proposal.evidence["adx"].edge < 0
    assert proposal.evidence["adx"].proposed_weight is None


def test_the_weights_are_normalised_across_the_signals_that_earned_one():
    rows = []
    for index, name in enumerate(("liquidity", "market_structure")):
        rows += series(80, mean=0.0012, seed=index + 1, start=index * 2000,
                       predicted="UP", signals={name: "BULL"})
        rows += series(80, mean=-0.0008, seed=index + 10, start=index * 2000 + 1000,
                       predicted="UP", signals={name: "BEAR"})
    proposal = SignalWeightResearch(minimum_samples=50).run(rows)
    assert sum(proposal.weighted.values()) == pytest.approx(1.0)


def test_a_proposal_is_never_applied():
    proposal = SignalWeightResearch(minimum_samples=50).run(series(10, seed=1))
    assert proposal.as_dict()["applied"] is False
    assert "not a configuration change" in proposal.as_dict()["disclaimer"]


def test_the_research_module_never_writes_to_the_strategy_weights():
    source = inspect.getsource(SignalWeightResearch)
    assert "DEFAULT_WEIGHTS[" not in source
    assert "DEFAULT_WEIGHTS.update" not in source


def test_the_comparison_with_configured_weights_is_reporting_only():
    proposal = SignalWeightResearch(minimum_samples=50).run(series(10, seed=1))
    payload = SignalWeightResearch().compare_with_configured(proposal)
    assert payload["applied"] is False
    assert isinstance(payload["comparison"], list)


def test_configured_weights_are_unchanged_by_running_the_research():
    from strategy.scoring import DEFAULT_WEIGHTS

    before = dict(DEFAULT_WEIGHTS)
    rows = series(80, mean=0.0012, seed=1, predicted="UP", signals={"liquidity": "BULL"})
    SignalWeightResearch(minimum_samples=10).run(rows)
    assert dict(DEFAULT_WEIGHTS) == before


@pytest.mark.parametrize("value,expected", [("BULL", 1), ("BEAR", -1), ("NEUTRAL", 0),
                                            (None, 0), ("UP", 1), ("SELL", -1)])
def test_the_direction_helper_reads_the_signal_vocabulary(value, expected):
    assert direction_of(value) == expected
