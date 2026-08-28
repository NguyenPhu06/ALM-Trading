"""High-confidence failures (section 16).

    confidence = 0.82
    prediction = BULL
    actual     = BEAR
    => HIGH_CONFIDENCE_FAILURE = true

A model that is wrong while unsure is behaving correctly. A model that is wrong
while sure is the failure this section exists to surface.
"""
from dataclasses import replace

import pytest

from ai.performance.errors import ErrorAnalyzer, ErrorClass
from config.settings import load_yaml
from monitoring.alerts import AlertEngine, AlertRouter, AlertType
from tests.phase14_helpers import observation, outcome


def classify(*, confidence, predicted="BUY", market_return=-0.001, threshold=0.75):
    sign = -1.0 if predicted.upper() in {"SELL", "SHORT"} else 1.0
    signed = sign * market_return
    return ErrorAnalyzer(high_confidence_threshold=threshold).classify(
        observation(direction=predicted, confidence=confidence),
        outcome(direction=predicted, future_return=signed, net=signed - 0.00012))


# ----------------------------------------------------------- the threshold
def test_the_threshold_comes_from_configuration():
    configured = load_yaml().get("phase_14", {}).get("high_confidence_threshold")
    assert configured is not None
    assert ErrorAnalyzer().high_confidence_threshold == pytest.approx(float(configured))


def test_the_documented_example_is_a_high_confidence_failure():
    result = classify(confidence=0.82)
    assert result.high_confidence_failure is True
    assert ErrorClass.HIGH_CONFIDENCE_FAILURE in result.tags
    assert result.primary is ErrorClass.FALSE_BULL


def test_confidence_exactly_at_the_threshold_counts():
    assert classify(confidence=0.75, threshold=0.75).high_confidence_failure is True


def test_confidence_just_below_the_threshold_does_not():
    result = classify(confidence=0.7499, threshold=0.75)
    assert result.high_confidence_failure is False
    assert ErrorClass.LOW_CONFIDENCE_FAILURE in result.tags


def test_a_confident_but_correct_prediction_is_not_a_failure():
    result = classify(confidence=0.95, market_return=0.002)
    assert result.correct
    assert result.high_confidence_failure is False


def test_a_missing_confidence_is_never_a_high_confidence_failure():
    analysis = ErrorAnalyzer(high_confidence_threshold=0.75).classify(
        replace(observation(direction="BUY"), nn_confidence=None),
        outcome(direction="BUY", future_return=-0.001, net=-0.0011))
    assert analysis.high_confidence_failure is False
    assert ErrorClass.LOW_CONFIDENCE_FAILURE in analysis.tags


def test_a_wrong_confident_sell_is_also_flagged():
    result = classify(confidence=0.90, predicted="SELL", market_return=0.002)
    assert result.high_confidence_failure is True
    assert result.primary is ErrorClass.FALSE_BEAR


# --------------------------------------------------------------- reporting
def test_the_summary_counts_high_confidence_failures():
    analyses = [classify(confidence=0.9) for _ in range(2)]
    analyses += [classify(confidence=0.4) for _ in range(3)]
    summary = ErrorAnalyzer(high_confidence_threshold=0.75).summarize(analyses)
    assert summary["high_confidence_failures"] == 2
    assert summary["high_confidence_failure_rate"] == pytest.approx(0.4)


def test_the_summary_reports_the_threshold_it_used():
    summary = ErrorAnalyzer(high_confidence_threshold=0.8).summarize([classify(confidence=0.9)])
    assert summary["high_confidence_threshold"] == pytest.approx(0.8)


def test_the_worst_failures_are_listed_most_confident_first():
    analyses = [classify(confidence=level) for level in (0.80, 0.95, 0.85)]
    summary = ErrorAnalyzer(high_confidence_threshold=0.75).summarize(analyses)
    confidences = [item["confidence"] for item in summary["worst"]]
    assert confidences == sorted(confidences, reverse=True)
    assert confidences[0] == pytest.approx(0.95)


def test_the_worst_list_is_bounded():
    analyses = [classify(confidence=0.9) for _ in range(30)]
    summary = ErrorAnalyzer(high_confidence_threshold=0.75).summarize(analyses)
    assert len(summary["worst"]) == 10


def test_only_failures_appear_in_the_worst_list():
    analyses = [classify(confidence=0.99, market_return=0.002) for _ in range(5)]
    summary = ErrorAnalyzer(high_confidence_threshold=0.75).summarize(analyses)
    assert summary["worst"] == []


# ------------------------------------------------------------------ alert
def test_a_high_confidence_failure_raises_its_own_alert():
    router = AlertRouter(AlertEngine())
    alerts = router.high_confidence_failure(analysis=classify(confidence=0.82))
    assert alerts[0].alert_type is AlertType.HIGH_CONFIDENCE_FAILURE
    assert "0.82" in alerts[0].message


def test_the_alert_carries_the_prediction_and_the_outcome():
    router = AlertRouter(AlertEngine())
    alert = router.high_confidence_failure(analysis=classify(confidence=0.82))[0]
    assert alert.context["predicted"] == "BUY"
    assert alert.context["actual"] == "DOWN"
    assert alert.context["high_confidence_failure"] is True
