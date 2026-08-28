"""Regime learning (section 17): where the model works, fails, and misleads."""
import pytest

from ai.performance.segments import (
    REGIME_SEGMENTS,
    ForwardSegmentLearner,
    SegmentVerdict,
)
from tests.phase14_helpers import NOW, performance_entries


def learner(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    kwargs.setdefault("calibration_gap_threshold", 0.20)
    return ForwardSegmentLearner(**kwargs)


def test_every_documented_regime_is_a_segment():
    assert set(REGIME_SEGMENTS) == {"STRONG_BULL", "BULL", "RANGE", "BEAR", "STRONG_BEAR",
                                    "UNKNOWN"}


def test_all_six_regimes_are_reported_even_when_empty():
    report = learner().by_regime(performance_entries(40, regimes=("BULL",), now=NOW))
    assert set(report.segments) == set(REGIME_SEGMENTS)
    assert report.segments["STRONG_BEAR"].samples == 0


def test_a_profitable_regime_with_enough_samples_works():
    report = learner().by_regime(performance_entries(40, net=0.0006, correct=True,
                                                     confidence=0.6, regimes=("BULL",),
                                                     now=NOW))
    assert report.segments["BULL"].verdict is SegmentVerdict.WORKS
    assert "BULL" in report.works


def test_a_losing_regime_fails():
    report = learner().by_regime(performance_entries(40, net=-0.0006, correct=False,
                                                     confidence=0.5, regimes=("BEAR",),
                                                     now=NOW))
    assert report.segments["BEAR"].verdict is SegmentVerdict.FAILS
    assert "BEAR" in report.fails


def test_a_thin_regime_is_never_judged():
    report = learner().by_regime(performance_entries(5, regimes=("RANGE",), now=NOW))
    segment = report.segments["RANGE"]
    assert segment.samples == 5
    assert not segment.reliable
    assert segment.verdict is SegmentVerdict.INSUFFICIENT_DATA


def test_a_thin_regime_still_reports_its_numbers():
    """Hiding the figures is worse than labelling them unreliable."""
    report = learner().by_regime(performance_entries(5, net=0.001, regimes=("RANGE",),
                                                     now=NOW))
    segment = report.segments["RANGE"]
    assert segment.expectancy == pytest.approx(0.001)
    assert segment.win_rate == pytest.approx(1.0)


def test_a_profitable_segment_the_model_is_wrong_about_is_misleading():
    """Profitable, but the model does not know why: the reserved case."""
    entries = performance_entries(40, net=0.0006, correct=False, confidence=0.95,
                                  regimes=("BULL",), now=NOW)
    report = learner().by_regime(entries)
    segment = report.segments["BULL"]
    assert segment.calibration_gap == pytest.approx(0.95)
    assert segment.verdict is SegmentVerdict.MISLEADING_CONFIDENCE
    assert "BULL" in report.misleading


def test_a_small_calibration_gap_is_not_misleading():
    entries = performance_entries(40, net=0.0006, correct=True, confidence=0.9,
                                  regimes=("BULL",), now=NOW)
    report = learner().by_regime(entries)
    assert report.segments["BULL"].calibration_gap == pytest.approx(-0.1)
    assert report.segments["BULL"].verdict is SegmentVerdict.WORKS


def test_a_losing_regime_the_model_was_sure_about_reports_both_facts():
    """The verdict names the money problem; `overconfident` names the other one."""
    entries = performance_entries(40, net=-0.0006, correct=False, confidence=0.9,
                                  regimes=("BEAR",), now=NOW)
    report = learner().by_regime(entries)
    segment = report.segments["BEAR"]
    assert segment.verdict is SegmentVerdict.FAILS
    assert segment.overconfident is True
    assert "BEAR" in report.overconfident
    assert "BEAR" not in report.misleading


def test_a_profitable_model_can_still_fail_in_one_regime():
    """The mistake section 17 exists to prevent."""
    entries = (performance_entries(40, net=0.0012, correct=True, regimes=("BULL",), now=NOW)
               + performance_entries(40, net=-0.0009, correct=False, regimes=("BEAR",),
                                     now=NOW))
    report = learner().by_regime(entries)
    assert "BULL" in report.works
    assert "BEAR" in report.fails


def test_an_unrecognised_regime_lands_in_unknown():
    entries = performance_entries(35, regimes=("SIDEWAYS_ISH",), now=NOW)
    report = learner().by_regime(entries)
    assert report.segments["UNKNOWN"].samples == 35


def test_each_segment_reports_the_documented_metrics():
    payload = learner().by_regime(
        performance_entries(40, regimes=("BULL",), now=NOW)).segments["BULL"].as_dict()
    for field in ("samples", "reliable", "verdict", "accuracy", "expectancy", "win_rate",
                  "profit_factor", "net_pnl", "max_drawdown", "average_mae", "average_mfe",
                  "average_confidence", "calibration_gap", "calibration"):
        assert field in payload, field


def test_the_report_lists_only_reliable_segments_as_reliable():
    entries = (performance_entries(40, regimes=("BULL",), now=NOW)
               + performance_entries(4, regimes=("BEAR",), now=NOW))
    report = learner().by_regime(entries)
    assert report.reliable_segments == ("BULL",)


def test_the_minimum_sample_floor_is_configurable():
    report = ForwardSegmentLearner(minimum_samples=3).by_regime(
        performance_entries(5, regimes=("RANGE",), now=NOW))
    assert report.segments["RANGE"].reliable


def test_the_serialised_report_names_the_three_verdict_groups():
    payload = learner().by_regime(performance_entries(40, regimes=("BULL",),
                                                      now=NOW)).as_dict()
    for key in ("works", "fails", "misleading_confidence", "reliable_segments"):
        assert key in payload
