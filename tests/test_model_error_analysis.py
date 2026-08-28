"""Classifying wrong predictions (section 15).

Every incorrect prediction gets one primary class plus contributing tags. The
tags describe *disagreement* between the prediction and what the observation
itself recorded; none of them claims the tagged component caused the failure.
"""
from dataclasses import replace

import pytest

from ai.performance.errors import ErrorAnalyzer, ErrorClass, direction_of
from tests.phase14_helpers import observation, outcome


def analyzer(**kwargs):
    kwargs.setdefault("high_confidence_threshold", 0.75)
    return ErrorAnalyzer(**kwargs)


def classify(*, predicted="BUY", market_return=-0.0009, confidence=0.60, regime="BULL",
             session="LONDON", context=None, **kwargs):
    """`market_return` is the market's move; the observation's return is derived."""
    record = observation(direction=predicted, confidence=confidence, regime=regime,
                         session=session)
    if context:
        record = replace(record, context={**record.context, **context})
    sign = -1.0 if predicted.upper() in {"SELL", "SHORT"} else 1.0
    signed = sign * market_return
    result = outcome(direction=predicted, future_return=signed, net=signed - 0.00012)
    return analyzer(**kwargs).classify(record, result)


# --------------------------------------------------- direction vocabulary
def test_the_direction_helper_reads_both_vocabularies():
    assert direction_of("BUY") == direction_of("UP") == direction_of("BULL") == 1
    assert direction_of("SELL") == direction_of("DOWN") == direction_of("BEAR") == -1
    assert direction_of("WAIT") == direction_of(None) == 0


# ------------------------------------------------------ the eleven classes
def test_every_documented_error_class_exists():
    assert {str(item) for item in ErrorClass} == {
        "FALSE_BULL", "FALSE_BEAR", "FALSE_NEUTRAL", "LOW_CONFIDENCE_FAILURE",
        "HIGH_CONFIDENCE_FAILURE", "REGIME_FAILURE", "SESSION_FAILURE",
        "LIQUIDITY_FAILURE", "STRUCTURE_FAILURE", "INDICATOR_FAILURE", "UNKNOWN"}


def test_a_wrong_bull_call_is_a_false_bull():
    assert classify(predicted="BUY", market_return=-0.001).primary is ErrorClass.FALSE_BULL


def test_a_wrong_bear_call_is_a_false_bear():
    assert classify(predicted="SELL", market_return=0.001).primary is ErrorClass.FALSE_BEAR


def test_a_missed_move_is_a_false_neutral():
    assert classify(predicted="WAIT", market_return=0.002).primary is ErrorClass.FALSE_NEUTRAL


# ------------------------------------------------------- correct is correct
def test_a_correct_buy_is_not_an_error():
    result = classify(predicted="BUY", market_return=0.002)
    assert result.correct
    assert result.tags == ()
    assert result.context["note"] == "CORRECT_PREDICTION"


def test_a_correct_sell_is_not_an_error():
    """A profitable SELL must never be classified as a wrong prediction."""
    result = classify(predicted="SELL", market_return=-0.002)
    assert result.correct
    assert result.actual == "DOWN"
    assert not result.high_confidence_failure


# ---------------------------------------------------------- context tags
def test_a_wrong_call_against_the_regime_is_tagged():
    result = classify(predicted="BUY", market_return=-0.001, regime="BEAR")
    assert ErrorClass.REGIME_FAILURE in result.tags


def test_a_wrong_call_with_the_regime_is_not_regime_tagged():
    result = classify(predicted="BUY", market_return=-0.001, regime="BULL")
    assert ErrorClass.REGIME_FAILURE not in result.tags


def test_a_weak_session_is_tagged():
    result = classify(predicted="BUY", market_return=-0.001, session="ASIA",
                      weak_sessions=("ASIA",))
    assert ErrorClass.SESSION_FAILURE in result.tags


def test_a_session_not_marked_weak_is_not_tagged():
    result = classify(predicted="BUY", market_return=-0.001, session="LONDON",
                      weak_sessions=("ASIA",))
    assert ErrorClass.SESSION_FAILURE not in result.tags


@pytest.mark.parametrize("key,tag", [
    ("structure_direction", ErrorClass.STRUCTURE_FAILURE),
    ("indicator_direction", ErrorClass.INDICATOR_FAILURE),
    ("liquidity_direction", ErrorClass.LIQUIDITY_FAILURE),
])
def test_a_contradicting_component_is_tagged(key, tag):
    result = classify(predicted="BUY", market_return=-0.001, context={key: "BEAR"})
    assert tag in result.tags


@pytest.mark.parametrize("key,tag", [
    ("structure_direction", ErrorClass.STRUCTURE_FAILURE),
    ("indicator_direction", ErrorClass.INDICATOR_FAILURE),
    ("liquidity_direction", ErrorClass.LIQUIDITY_FAILURE),
])
def test_an_agreeing_component_is_not_tagged(key, tag):
    result = classify(predicted="BUY", market_return=-0.001, context={key: "BULL"})
    assert tag not in result.tags


def test_an_unreadable_context_produces_no_component_tag():
    result = classify(predicted="BUY", market_return=-0.001,
                      context={"structure_direction": None})
    assert ErrorClass.STRUCTURE_FAILURE not in result.tags


# ------------------------------------------------------------- the summary
def test_the_summary_counts_classes_and_accuracy():
    analyses = [classify(predicted="BUY", market_return=-0.001) for _ in range(3)]
    analyses += [classify(predicted="BUY", market_return=0.002) for _ in range(7)]
    summary = analyzer().summarize(analyses)
    assert summary["samples"] == 10
    assert summary["incorrect"] == 3
    assert summary["accuracy"] == pytest.approx(0.7)
    assert summary["by_class"]["FALSE_BULL"] == 3


def test_the_summary_groups_errors_by_regime_and_session():
    analyses = [classify(predicted="BUY", market_return=-0.001, regime="BEAR",
                         session="ASIA")]
    summary = analyzer().summarize(analyses)
    assert summary["by_regime"] == {"BEAR": 1}
    assert summary["by_session"] == {"ASIA": 1}


def test_a_summary_of_only_correct_predictions_reports_no_failures():
    analyses = [classify(predicted="BUY", market_return=0.002) for _ in range(5)]
    summary = analyzer().summarize(analyses)
    assert summary["incorrect"] == 0
    assert summary["by_class"] == {}
    assert summary["high_confidence_failure_rate"] == 0.0


def test_the_analysis_serialises_every_field():
    payload = classify(predicted="BUY", market_return=-0.001).as_dict()
    for field in ("observation_id", "correct", "predicted", "actual", "confidence",
                  "primary", "tags", "high_confidence_failure", "net_pnl", "regime",
                  "session", "timeframe"):
        assert field in payload, field


def test_analyze_classifies_a_batch():
    pairs = [(observation(index, direction="BUY"),
              outcome(index, future_return=-0.001, net=-0.0011)) for index in range(4)]
    results = analyzer().analyze(pairs)
    assert len(results) == 4
    assert all(item.primary is ErrorClass.FALSE_BULL for item in results)
