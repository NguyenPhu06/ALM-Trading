"""The weekly review (section 20).

A research report rather than an operational one: is the Champion still the
Champion, is the network contributing anything, does DCA earn its place, and is
there an edge. The honest answer to the last question is expected to be
INSUFFICIENT_DATA for a long time, and the report says so.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from validation.reviews import ReviewBuilder
from validation.segments import SegmentAnalyzer
from tests.phase17_helpers import trades

WEEK = date(2026, 8, 24)


def review(**overrides):
    payload = dict(week_start=WEEK)
    payload.update(overrides)
    return ReviewBuilder().weekly(**payload)


# ---------------------------------------------------------------- the fields
def test_the_report_carries_every_declared_section():
    """Section 20, section for section."""
    payload = review().as_dict()
    for name in ("champion_performance", "strategy_comparison", "nn_contribution",
                 "indicator_contribution", "dca_contribution", "session_performance",
                 "regime_performance", "timeframe_performance", "execution_quality",
                 "model_drift", "edge_status"):
        assert name in payload


def test_the_week_runs_from_its_start_to_six_days_later():
    payload = review().as_dict()
    assert payload["week_start"] == "2026-08-24"
    assert payload["week_end"] == "2026-08-30"


def test_the_report_states_it_is_not_a_backtest():
    note = review().as_dict()["note"]
    assert "not a backtest" in note


# --------------------------------------------------------------- the champion
def test_a_missing_champion_is_reported_as_a_reason():
    report = review()
    assert report.champion_strategy is None
    assert "NO_CHAMPION_STRATEGY" in report.reasons
    assert "NO_CHAMPION_PERFORMANCE" in report.reasons


def test_a_named_champion_is_carried_through():
    report = review(champion_strategy="smc:v1", champion_model="model-7",
                    champion_performance={"samples": 40, "expectancy": 0.0004})
    assert report.champion_strategy == "smc:v1"
    assert report.champion_model == "model-7"
    assert report.champion_performance["samples"] == 40
    assert "NO_CHAMPION_STRATEGY" not in report.reasons


# ------------------------------------------------------------- the contributions
def test_the_contributions_are_carried_through():
    report = review(nn_contribution={"verdict": "NN_VALUE_NOT_PROVEN"},
                    indicator_contribution={"verdict": "IMPROVES"},
                    dca_contribution={"verdict": "REJECTED_TAIL_RISK"})
    assert report.nn_contribution["verdict"] == "NN_VALUE_NOT_PROVEN"
    assert report.indicator_contribution["verdict"] == "IMPROVES"
    assert report.dca_contribution["verdict"] == "REJECTED_TAIL_RISK"


def test_the_segment_cuts_are_carried_through():
    segments = SegmentAnalyzer().all(trades(40))
    report = review(segments=segments)
    assert report.regime_performance["dimension"] == "regime"
    assert report.session_performance["dimension"] == "session"
    assert report.timeframe_performance["dimension"] == "timeframe"


def test_execution_quality_and_drift_are_carried_through():
    report = review(execution_quality={"rejection_rate": 0.02},
                    model_drift={"prediction_drift": 0.05})
    assert report.execution_quality["rejection_rate"] == 0.02
    assert report.model_drift["prediction_drift"] == 0.05


# ---------------------------------------------------------------- the edge
def test_the_default_edge_status_is_insufficient_data():
    report = review()
    assert report.edge_status == "INSUFFICIENT_DATA"
    assert "INSUFFICIENT_DATA" in report.reasons


def test_a_stated_edge_status_is_reported_verbatim():
    report = review(edge_status="NO_EDGE")
    assert report.edge_status == "NO_EDGE"
    assert "INSUFFICIENT_DATA" not in report.reasons


# ---------------------------------------------------------------- the service
def test_the_service_builds_a_weekly_review(db_session):
    from database.repositories.validation import ValidationRepository
    from tests.phase16_helpers import settings
    from validation.service import ValidationService

    service = ValidationService(ValidationRepository(db_session), settings=settings())
    report = service.weekly_review(week_start=WEEK)
    assert report["week_start"] == "2026-08-24"
    assert report["edge_status"] == "INSUFFICIENT_DATA"
    assert report["regime_performance"]["dimension"] == "regime"


def test_the_service_defaults_to_the_current_week(db_session):
    from database.repositories.validation import ValidationRepository
    from tests.phase16_helpers import settings
    from validation.service import ValidationService

    service = ValidationService(ValidationRepository(db_session), settings=settings())
    report = service.weekly_review(now=datetime(2026, 8, 28, 12, tzinfo=timezone.utc))
    assert report["week_start"] == "2026-08-24", "Monday of that week"


def test_the_weekly_endpoint_reports_no_evidence_yet(client):
    body = client.get("/validation/review/weekly").json()["data"]
    assert body["edge_status"] == "INSUFFICIENT_DATA"
    assert body["champion_strategy"] is None
    assert "not a backtest" in body["note"]
