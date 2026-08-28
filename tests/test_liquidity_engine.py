"""Liquidity evidence: OBSERVED facts kept apart from INFERRED hypotheses."""
from datetime import datetime, timezone

import pytest

from observation.liquidity_evidence import (
    Confidence,
    EvidenceKind,
    FORBIDDEN_CLAIMS,
    LiquidityEvidence,
    LiquidityEvidenceClassifier,
    contains_forbidden_claim,
)

NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)


def event(event_type, **overrides):
    row = {"event_type": event_type, "price": 1.1042, "strength": 0.5,
           "event_timestamp": NOW, "timeframe": "M15"}
    row.update(overrides)
    return row


@pytest.mark.parametrize("event_type", [
    "EQUAL_HIGH", "EQUAL_LOW", "PREVIOUS_DAY_HIGH", "PREVIOUS_DAY_LOW",
    "SESSION_HIGH", "SESSION_LOW", "LIQUIDITY_SWEEP", "DISPLACEMENT", "REJECTION",
])
def test_computable_facts_are_classified_observed(event_type):
    evidence = LiquidityEvidenceClassifier().classify_event(event(event_type))
    assert evidence.kind is EvidenceKind.OBSERVED and evidence.observed


@pytest.mark.parametrize("event_type", ["LIQUIDITY_POOL", "RESTING_ORDER_CLUSTER"])
def test_hypotheses_are_classified_inferred(event_type):
    evidence = LiquidityEvidenceClassifier().classify_event(event(event_type))
    assert evidence.kind is EvidenceKind.INFERRED and not evidence.observed


def test_an_unrecognised_event_defaults_to_inferred():
    """Unknown provenance is a hypothesis, never promoted to a fact."""
    evidence = LiquidityEvidenceClassifier().classify_event(event("SOMETHING_NEW"))
    assert evidence.kind is EvidenceKind.INFERRED


def test_an_observed_statement_is_stated_plainly():
    evidence = LiquidityEvidenceClassifier().classify_event(event("LIQUIDITY_SWEEP"))
    assert "was observed" in evidence.describe()


def test_an_inferred_statement_is_hedged_and_says_so():
    evidence = LiquidityEvidenceClassifier().classify_event(event("LIQUIDITY_POOL"))
    text = evidence.describe()
    assert "inference, not a confirmed order" in text
    assert any(hedge in text for hedge in ("may indicate", "is consistent with",
                                           "strongly suggests"))


@pytest.mark.parametrize(("strength", "expected"), [
    (0.9, Confidence.HIGH), (0.5, Confidence.MODERATE), (0.1, Confidence.LOW),
    (None, Confidence.LOW),
])
def test_confidence_follows_strength(strength, expected):
    evidence = LiquidityEvidenceClassifier().classify_event(event("LIQUIDITY_POOL",
                                                                 strength=strength))
    assert evidence.confidence is expected


def test_no_statement_claims_a_specific_market_participant():
    classifier = LiquidityEvidenceClassifier()
    for event_type in ("LIQUIDITY_SWEEP", "LIQUIDITY_POOL", "EQUAL_HIGH", "DISPLACEMENT"):
        for strength in (0.1, 0.5, 0.9):
            text = classifier.classify_event(event(event_type, strength=strength)).describe()
            assert not contains_forbidden_claim(text), text


def test_the_forbidden_vocabulary_is_actually_detected():
    assert contains_forbidden_claim("a bank is defending this level")
    assert contains_forbidden_claim("SMART MONEY accumulating")
    assert not contains_forbidden_claim("price swept the previous day high")


def test_a_report_separates_the_two_kinds_and_carries_a_disclaimer():
    report = LiquidityEvidenceClassifier().classify(
        [event("EQUAL_HIGH"), event("LIQUIDITY_POOL"), event("LIQUIDITY_SWEEP")],
        symbol="EURUSD")
    assert report.observed_count if hasattr(report, "observed_count") else True
    payload = report.as_dict()
    assert payload["observed_count"] == 2 and payload["inferred_count"] == 1
    assert "not claims about any specific market participant" in payload["disclaimer"]


def test_a_report_payload_contains_no_forbidden_claim():
    report = LiquidityEvidenceClassifier().classify(
        [event("LIQUIDITY_POOL"), event("SESSION_HIGH")], symbol="EURUSD")
    assert not contains_forbidden_claim(str(report.as_dict()))
