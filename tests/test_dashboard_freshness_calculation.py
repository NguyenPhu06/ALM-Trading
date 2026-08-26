"""Freshness is measured from the source timestamp, not hardcoded.

Phase 9 shipped `data_age_seconds: 0` for every payload and derived `stale` only
from the quality string, so a three-day-old candle reported as live.
"""
from datetime import datetime, timedelta, timezone

from monitoring.dashboard import DEFAULT_MAX_AGE_SECONDS, envelope

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)


def test_age_is_measured_from_the_source_timestamp():
    result = envelope({}, quality="VALID", timestamp=NOW - timedelta(seconds=90), now=NOW)
    assert result["data_age_seconds"] == 90.
    assert result["last_update"] == NOW - timedelta(seconds=90)
    assert result["timestamp"] == NOW


def test_recent_valid_data_is_not_stale():
    result = envelope({}, quality="VALID", timestamp=NOW - timedelta(seconds=30), now=NOW)
    assert not result["stale"] and result["data_age_seconds"] == 30.


def test_data_older_than_the_budget_is_stale_even_when_quality_is_valid():
    result = envelope({}, quality="VALID", timestamp=NOW - timedelta(days=3), now=NOW)
    assert result["stale"] and result["data_age_seconds"] == 3 * 86400.


def test_boundary_is_deterministic_at_exactly_the_budget():
    at_budget = envelope({}, quality="VALID", timestamp=NOW - timedelta(seconds=DEFAULT_MAX_AGE_SECONDS), now=NOW)
    past_budget = envelope({}, quality="VALID", timestamp=NOW - timedelta(seconds=DEFAULT_MAX_AGE_SECONDS + 1), now=NOW)
    assert not at_budget["stale"] and past_budget["stale"]


def test_missing_source_timestamp_is_unknown_age_and_therefore_stale():
    result = envelope({}, quality="VALID", timestamp=None, now=NOW)
    assert result["data_age_seconds"] is None and result["stale"] and result["last_update"] is None


def test_unavailable_or_invalid_quality_stays_stale_regardless_of_age():
    for quality in ("UNAVAILABLE", "INVALID", "STALE"):
        result = envelope({}, quality=quality, timestamp=NOW, now=NOW)
        assert result["stale"], quality


def test_naive_source_timestamps_are_read_as_utc():
    result = envelope({}, quality="VALID", timestamp=datetime(2026, 8, 26, 11, 59, 30), now=NOW)
    assert result["data_age_seconds"] == 30.


def test_future_source_timestamp_clamps_to_zero_rather_than_reporting_negative_age():
    result = envelope({}, quality="VALID", timestamp=NOW + timedelta(seconds=60), now=NOW)
    assert result["data_age_seconds"] == 0.


def test_custom_budget_overrides_the_default():
    result = envelope({}, quality="VALID", timestamp=NOW - timedelta(seconds=45), now=NOW, max_age_seconds=30)
    assert result["stale"] and result["max_age_seconds"] == 30


def test_dashboard_endpoints_expose_freshness_fields(client):
    for endpoint in ("/dashboard/overview", "/dashboard/risk", "/dashboard/positions",
                     "/dashboard/journal", "/dashboard/alerts"):
        body = client.get(endpoint).json()
        assert {"last_update", "data_age_seconds", "stale", "max_age_seconds"} <= body.keys(), endpoint


def test_empty_paper_collections_are_reported_unavailable_not_valid(client):
    """An empty journal is missing data, not valid data."""
    from api.main import paper_service

    paper_service.__init__()
    for endpoint in ("/dashboard/positions", "/dashboard/journal", "/dashboard/performance"):
        body = client.get(endpoint).json()
        assert body["data_quality"] == "UNAVAILABLE", endpoint
        assert body["stale"], endpoint
