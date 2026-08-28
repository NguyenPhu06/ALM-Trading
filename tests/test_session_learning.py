"""Session learning (section 18).

The named sessions in this codebase are ASIA, LONDON, NEW_YORK,
LONDON_NEW_YORK_OVERLAP and OFF_SESSION; anything else a provider hands back is
collected under CUSTOM rather than silently dropped.
"""
import pytest

from ai.performance.segments import (
    SESSION_SEGMENTS,
    ForwardSegmentLearner,
    SegmentVerdict,
)
from tests.phase14_helpers import NOW, performance_entries


def learner(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return ForwardSegmentLearner(**kwargs)


def test_every_documented_session_is_a_segment():
    assert set(SESSION_SEGMENTS) == {"ASIA", "LONDON", "NEW_YORK",
                                     "LONDON_NEW_YORK_OVERLAP", "OFF_SESSION", "CUSTOM"}


def test_the_overlap_session_is_reported_separately():
    entries = performance_entries(35, sessions=("LONDON_NEW_YORK_OVERLAP",), now=NOW)
    report = learner().by_session(entries)
    assert report.segments["LONDON_NEW_YORK_OVERLAP"].samples == 35


def test_an_unnamed_session_lands_in_custom():
    report = learner().by_session(performance_entries(35, sessions=("SYDNEY",), now=NOW))
    assert report.segments["CUSTOM"].samples == 35
    assert report.segments["ASIA"].samples == 0


def test_sessions_are_compared_independently():
    entries = (performance_entries(40, net=0.0009, correct=True, sessions=("LONDON",),
                                   now=NOW)
               + performance_entries(40, net=-0.0007, correct=False, confidence=0.4,
                                     sessions=("ASIA",), now=NOW))
    report = learner().by_session(entries)
    assert "LONDON" in report.works
    assert "ASIA" in report.fails


def test_prediction_accuracy_is_reported_per_session():
    entries = (performance_entries(20, correct=True, sessions=("LONDON",), now=NOW)
               + performance_entries(20, correct=False, sessions=("LONDON",), now=NOW))
    segment = learner().by_session(entries).segments["LONDON"]
    assert segment.accuracy == pytest.approx(0.5)


def test_expectancy_is_reported_per_session():
    segment = learner().by_session(
        performance_entries(40, net=0.0005, sessions=("NEW_YORK",),
                            now=NOW)).segments["NEW_YORK"]
    assert segment.expectancy == pytest.approx(0.0005)
    assert segment.net_pnl == pytest.approx(0.02)


def test_drawdown_is_reported_per_session():
    segment = learner().by_session(
        performance_entries(40, net=-0.0005, sessions=("ASIA",),
                            now=NOW)).segments["ASIA"]
    assert segment.max_drawdown == pytest.approx(0.02)


def test_mae_and_mfe_are_reported_per_session():
    segment = learner().by_session(
        performance_entries(40, sessions=("LONDON",), now=NOW)).segments["LONDON"]
    assert segment.average_mae == pytest.approx(-0.0003)
    assert segment.average_mfe == pytest.approx(0.0006)


def test_spread_is_reported_per_session():
    """Section 18 compares spread across sessions, so it must be carried through."""
    segment = learner().by_session(
        performance_entries(40, sessions=("ASIA",), now=NOW)).segments["ASIA"]
    assert segment.average_spread == pytest.approx(0.00010)


def test_a_session_without_spread_data_reports_none():
    from dataclasses import replace

    entries = [replace(entry, spread=None)
               for entry in performance_entries(40, sessions=("ASIA",), now=NOW)]
    assert learner().by_session(entries).segments["ASIA"].average_spread is None


def test_a_thin_session_is_not_judged():
    report = learner().by_session(performance_entries(6, sessions=("OFF_SESSION",),
                                                      now=NOW))
    assert report.segments["OFF_SESSION"].verdict is SegmentVerdict.INSUFFICIENT_DATA


def test_calibration_is_reported_per_session():
    segment = learner().by_session(
        performance_entries(40, correct=True, confidence=0.8, sessions=("LONDON",),
                            now=NOW)).segments["LONDON"]
    assert segment.calibration["samples"] == 40
    assert segment.calibration["brier_score"] == pytest.approx(0.04)


def test_all_three_dimensions_are_produced_together():
    payload = learner().all_dimensions(performance_entries(40, now=NOW))
    assert set(payload) == {"regime", "session", "timeframe"}
    assert payload["session"]["dimension"] == "session"
