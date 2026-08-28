"""Per-regime metrics (sections 20, 21).

An aggregate score hides a model that works in one regime and fails in
another, so every segment reports its own sample size and reliability flag.
"""
import numpy as np
import pytest

from ai.evaluation.segmented import SegmentedEvaluator, trading_metrics
from ai.evaluation.segmented import REGIMES


def sample(count=120, seed=4):
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, 3, count)
    probabilities = rng.dirichlet(np.ones(3), count)
    returns = rng.normal(0.0002, 0.001, count)
    segments = rng.choice(["BULL", "BEAR", "RANGE"], size=count)
    return labels, probabilities, returns, segments


def test_every_regime_appears_in_the_report():
    labels, probabilities, returns, segments = sample()
    report = SegmentedEvaluator(minimum_samples=10).by_regime(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    assert set(report.segments) == set(REGIMES)
    assert report.dimension == "regime"


def test_an_absent_regime_reports_zero_samples():
    labels, probabilities, returns, segments = sample()
    report = SegmentedEvaluator(minimum_samples=10).by_regime(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    assert report.segments["STRONG_BULL"].samples == 0
    assert not report.segments["STRONG_BULL"].reliable


def test_a_segment_below_the_minimum_is_not_reliable():
    labels, probabilities, returns, segments = sample(count=30)
    report = SegmentedEvaluator(minimum_samples=100).by_regime(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    assert all(not item.reliable for item in report.segments.values())
    assert report.reliable_segments == ()


def test_the_weakest_reliable_segment_is_identified():
    labels, probabilities, returns, segments = sample(count=300)
    report = SegmentedEvaluator(minimum_samples=20).by_regime(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    weakest = report.weakest
    assert weakest is not None and weakest.reliable
    for item in report.segments.values():
        if item.reliable and item.expectancy is not None:
            assert weakest.expectancy <= item.expectancy


def test_each_segment_reports_trading_metrics():
    labels, probabilities, returns, segments = sample(count=300)
    report = SegmentedEvaluator(minimum_samples=20).by_regime(
        labels=labels, probabilities=probabilities, returns=returns, segments=segments)
    item = report.segments["BULL"]
    for name in ("expectancy", "win_rate", "profit_factor", "average_win",
                 "average_loss", "max_drawdown"):
        assert getattr(item, name) is not None, name


def test_trading_metrics_handle_an_all_winning_series():
    metrics = trading_metrics([0.001, 0.002, 0.003])
    assert metrics["win_rate"] == 1.0
    assert metrics["profit_factor"] == float("inf")
    assert metrics["max_drawdown"] == 0.0


def test_trading_metrics_handle_an_empty_series():
    metrics = trading_metrics([])
    assert all(value is None for value in metrics.values())


def test_drawdown_is_measured_on_the_equity_curve():
    metrics = trading_metrics([0.01, -0.02, 0.005])
    assert metrics["max_drawdown"] == pytest.approx(0.02)
