"""Timeframe learning (section 19).

"Do not assume that a model that performs well on M5 also performs well on H1."
The test below states that as an executable claim.
"""
import pytest

from ai.performance.segments import (
    TIMEFRAME_SEGMENTS,
    ForwardSegmentLearner,
    SegmentVerdict,
)
from tests.phase14_helpers import NOW, performance_entries


def learner(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return ForwardSegmentLearner(**kwargs)


def test_every_documented_timeframe_is_a_segment():
    assert TIMEFRAME_SEGMENTS == ("D1", "H4", "H1", "M30", "M15", "M5")


def test_all_six_timeframes_are_reported_even_when_empty():
    report = learner().by_timeframe(performance_entries(40, timeframes=("M5",), now=NOW))
    assert set(report.segments) == set(TIMEFRAME_SEGMENTS)
    assert report.segments["D1"].samples == 0


def test_m5_success_says_nothing_about_h1():
    """The exact failure mode section 19 warns about."""
    entries = (performance_entries(40, net=0.0011, correct=True, timeframes=("M5",),
                                   now=NOW)
               + performance_entries(40, net=-0.0008, correct=False, confidence=0.4,
                                     timeframes=("H1",), now=NOW))
    report = learner().by_timeframe(entries)
    assert "M5" in report.works
    assert "H1" in report.fails
    assert report.segments["M5"].expectancy > 0 > report.segments["H1"].expectancy


def test_a_timeframe_is_judged_only_on_its_own_samples():
    entries = (performance_entries(40, net=0.0011, timeframes=("M5",), now=NOW)
               + performance_entries(40, net=-0.0008, timeframes=("H1",), now=NOW))
    report = learner().by_timeframe(entries)
    assert report.segments["M5"].samples == 40
    assert report.segments["H1"].samples == 40
    assert report.segments["M15"].samples == 0


def test_an_untested_timeframe_is_insufficient_data_not_a_pass():
    report = learner().by_timeframe(performance_entries(40, timeframes=("M5",), now=NOW))
    assert report.segments["H4"].verdict is SegmentVerdict.INSUFFICIENT_DATA
    assert "H4" not in report.works


def test_a_thin_timeframe_is_not_judged():
    entries = (performance_entries(40, timeframes=("M5",), now=NOW)
               + performance_entries(3, timeframes=("H4",), now=NOW))
    report = learner().by_timeframe(entries)
    assert report.segments["H4"].verdict is SegmentVerdict.INSUFFICIENT_DATA
    assert report.reliable_segments == ("M5",)


def test_entries_spread_across_timeframes_are_grouped_correctly():
    entries = performance_entries(60, timeframes=("M5", "M15", "H1"), now=NOW)
    report = learner(minimum_samples=10).by_timeframe(entries)
    assert report.segments["M5"].samples == 20
    assert report.segments["M15"].samples == 20
    assert report.segments["H1"].samples == 20


def test_an_unrecognised_timeframe_is_not_silently_counted_as_a_known_one():
    report = learner().by_timeframe(performance_entries(35, timeframes=("M3",), now=NOW))
    assert all(segment.samples == 0 for name, segment in report.segments.items()
               if name in TIMEFRAME_SEGMENTS)
    assert report.segments["UNKNOWN"].samples == 35


def test_each_timeframe_reports_its_own_metrics():
    payload = learner().by_timeframe(
        performance_entries(40, timeframes=("M5",), now=NOW)).segments["M5"].as_dict()
    assert payload["dimension"] == "timeframe"
    assert payload["segment"] == "M5"
    assert payload["win_rate"] == pytest.approx(1.0)


def test_the_aggregate_does_not_hide_a_failing_timeframe():
    entries = (performance_entries(80, net=0.0012, correct=True, timeframes=("M5",),
                                   now=NOW)
               + performance_entries(40, net=-0.0004, correct=False, confidence=0.4,
                                     timeframes=("H1",), now=NOW))
    overall = sum(entry.net_pnl for entry in entries)
    report = learner().by_timeframe(entries)
    assert overall > 0, "the model is profitable overall"
    assert "H1" in report.fails, "and still fails on H1"
