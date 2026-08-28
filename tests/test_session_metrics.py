"""Per-session metrics (sections 20, 21).

An aggregate score hides a model that works in one session and fails in
another, so every segment reports its own sample size and reliability flag.
"""
import numpy as np
import pytest

from ai.evaluation.segmented import SegmentedEvaluator, trading_metrics
from ai.evaluation.segmented import SESSIONS, TIMEFRAMES


def sample(count=240, seed=6):
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, 3, count)
    probabilities = rng.dirichlet(np.ones(3), count)
    returns = rng.normal(0.0001, 0.0012, count)
    segments = rng.choice(["LONDON", "NEW_YORK", "ASIA"], size=count)
    return labels, probabilities, returns, segments


def test_every_session_appears_in_the_report():
    labels, probabilities, returns, segments = sample()
    report = SegmentedEvaluator(minimum_samples=20).by_session(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    assert set(report.segments) == set(SESSIONS)
    assert report.dimension == "session"


def test_the_overlap_session_is_tracked_separately():
    assert "LONDON_NEW_YORK_OVERLAP" in SESSIONS


def test_sessions_with_data_are_reliable_above_the_minimum():
    labels, probabilities, returns, segments = sample()
    report = SegmentedEvaluator(minimum_samples=20).by_session(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    assert "LONDON" in report.reliable_segments


def test_a_timeframe_report_covers_every_timeframe():
    labels, probabilities, returns, _ = sample()
    segments = np.random.default_rng(1).choice(["M5", "M15", "H1"], size=len(labels))
    report = SegmentedEvaluator(minimum_samples=20).by_timeframe(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    assert set(report.segments) == set(TIMEFRAMES)
    assert report.dimension == "timeframe"


def test_m5_results_do_not_stand_in_for_higher_timeframes():
    """Each timeframe is scored on its own rows."""
    labels, probabilities, returns, _ = sample()
    segments = np.array(["M5"] * len(labels))
    report = SegmentedEvaluator(minimum_samples=20).by_timeframe(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    assert report.segments["M5"].samples == len(labels)
    assert report.segments["D1"].samples == 0
    assert not report.segments["D1"].reliable


def test_a_single_class_segment_still_reports_accuracy():
    labels = np.zeros(40, dtype=int)
    probabilities = np.tile([0.8, 0.1, 0.1], (40, 1))
    returns = np.full(40, 0.0005)
    segments = np.array(["LONDON"] * 40)
    report = SegmentedEvaluator(minimum_samples=10).by_session(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    assert report.segments["LONDON"].accuracy == pytest.approx(1.0)


def test_the_report_serialises():
    labels, probabilities, returns, segments = sample()
    payload = SegmentedEvaluator().by_session(
        labels=labels, probabilities=probabilities, returns=returns,
        segments=segments).as_dict()
    assert payload["dimension"] == "session" and "segments" in payload
