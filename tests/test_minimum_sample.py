"""Minimum samples, rolling windows and segments (sections 10, 11, 12, 15, 16).

Section 16 is the gate in front of every claim in Phase 17: an edge is never
declared from a tiny sample. These tests hold that line from four directions —
the requirements themselves, the rolling windows, the segment cells, and the
"where sufficient data exists" clause that stops a 90-day figure being computed
from four days of history.
"""
from datetime import datetime, timedelta, timezone

import pytest

from validation.segments import REGIMES, SESSIONS, TIMEFRAMES, SegmentAnalyzer
from validation.windows import (
    WINDOWS, EdgeStatus, RollingWindowEvaluator, SampleRequirements,
)
from tests.phase17_helpers import trades

NOW = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
LENIENT = SampleRequirements(minimum_signals=10, minimum_winning_signals=3,
                             minimum_losing_signals=3)


def evaluator(requirements=None, **kwargs):
    return RollingWindowEvaluator(requirements or LENIENT, **kwargs)


# ------------------------------------------------------------- section 16
def test_the_shipped_minimums_are_demanding():
    requirements = SampleRequirements.from_config()
    assert requirements.minimum_signals >= 100
    assert requirements.minimum_winning_signals >= 20
    assert requirements.minimum_losing_signals >= 20


def test_every_minimum_is_configurable():
    requirements = SampleRequirements.from_config({"minimum_signals": 7})
    assert requirements.minimum_signals == 7


def test_a_population_below_a_floor_reports_which_one():
    gaps = LENIENT.shortfalls(signals=5, wins=1, losses=1)
    assert set(gaps) == {"MINIMUM_SIGNALS", "MINIMUM_WINNING_SIGNALS",
                         "MINIMUM_LOSING_SIGNALS"}


def test_a_population_of_only_winners_still_misses_a_floor():
    """A sample with no losses tells you nothing about the downside."""
    assert "MINIMUM_LOSING_SIGNALS" in LENIENT.shortfalls(signals=50, wins=50, losses=0)


def test_a_population_that_clears_every_floor_reports_no_gaps():
    assert LENIENT.shortfalls(signals=50, wins=20, losses=20) == ()


# ------------------------------------------------------------- section 15
def test_the_seven_declared_windows_exist():
    assert [name for name, _ in WINDOWS] == ["24h", "3d", "7d", "14d", "30d", "60d", "90d"]


def test_a_tiny_sample_is_insufficient_data_not_an_edge():
    rows = trades(4, start=NOW - timedelta(hours=4))
    result = evaluator().evaluate(rows, window="24h", span=timedelta(hours=24), now=NOW)
    assert result.edge_status is EdgeStatus.INSUFFICIENT_DATA
    assert result.reliable is False


def test_a_window_longer_than_the_history_is_not_covered():
    """A 90d figure computed from a day of trading is not a 90d figure."""
    rows = trades(60, start=NOW - timedelta(hours=60), step=timedelta(hours=1))
    result = evaluator().evaluate(rows, window="90d", span=timedelta(days=90), now=NOW,
                                  earliest=NOW - timedelta(hours=60))
    assert result.covered is False
    assert "WINDOW_NOT_COVERED" in result.reasons
    assert result.edge_status is EdgeStatus.INSUFFICIENT_DATA


def test_a_covered_window_with_enough_samples_can_report_an_edge():
    rows = trades(30, start=NOW - timedelta(hours=30), step=timedelta(hours=1))
    result = evaluator().evaluate(rows, window="24h", span=timedelta(hours=24), now=NOW,
                                  earliest=NOW - timedelta(days=2))
    assert result.covered is True
    assert result.edge_status is EdgeStatus.EDGE_DETECTED
    assert result.samples > 0


def test_a_losing_population_reports_no_edge():
    """Wins outnumber losses, but the losses are bigger. Expectancy decides."""
    rows = trades(30, start=NOW - timedelta(hours=30))
    for row in rows:
        if row["net_pnl"] < 0:
            row["net_pnl"] = -5.0
    result = evaluator().evaluate(rows, window="24h", span=timedelta(hours=24), now=NOW,
                                  earliest=NOW - timedelta(days=2))
    assert result.win_rate > 0.5
    assert result.expectancy < 0
    assert result.edge_status is EdgeStatus.NO_EDGE


def test_rows_outside_the_window_are_excluded():
    rows = trades(30, start=NOW - timedelta(days=40), step=timedelta(hours=1))
    result = evaluator().evaluate(rows, window="24h", span=timedelta(hours=24), now=NOW)
    assert result.samples == 0


def test_an_edge_in_one_window_only_is_instability_not_an_edge():
    rows = trades(30, start=NOW - timedelta(hours=30), step=timedelta(hours=1))
    report = evaluator().all(rows, now=NOW)
    # The short window clears the floor; the long ones are not covered.
    assert report["edge_status"] in {str(EdgeStatus.EDGE_DETECTED),
                                     str(EdgeStatus.UNSTABLE_EDGE)}
    assert set(report["windows"]) == {name for name, _ in WINDOWS}


def test_an_empty_population_is_insufficient_data_everywhere():
    report = evaluator().all([], now=NOW)
    assert report["edge_status"] == str(EdgeStatus.INSUFFICIENT_DATA)
    assert all(row["edge_status"] == "INSUFFICIENT_DATA"
               for row in report["windows"].values())


def test_the_requirements_are_reported_with_the_windows():
    report = evaluator().all(trades(5), now=NOW)
    assert report["requirements"]["minimum_signals"] == LENIENT.minimum_signals


# --------------------------------------------------------- sections 10, 11, 12
def test_every_declared_regime_gets_a_cell():
    report = SegmentAnalyzer().by_regime(trades(10))
    assert set(REGIMES) <= set(report.cells)


def test_every_declared_session_gets_a_cell():
    report = SegmentAnalyzer().by_session(trades(10))
    assert set(SESSIONS) <= set(report.cells)


def test_every_declared_timeframe_gets_a_cell():
    report = SegmentAnalyzer().by_timeframe(trades(10))
    assert set(TIMEFRAMES) <= set(report.cells)


def test_a_cell_below_its_floor_is_reported_but_is_not_evidence():
    analyzer = SegmentAnalyzer(minimum_regime_samples=30)
    report = analyzer.by_regime(trades(5, regime="BEAR"))
    cell = report.cells["BEAR"]
    assert cell.samples == 5
    assert cell.reliable is False and "INSUFFICIENT_SAMPLES" in cell.reasons
    assert "BEAR" not in report.reliable_cells


def test_best_and_worst_are_named_only_among_reliable_cells():
    analyzer = SegmentAnalyzer(minimum_regime_samples=30)
    report = analyzer.by_regime(trades(5, regime="BEAR"))
    assert report.best is None and report.worst is None


def test_a_reliable_cell_can_be_ranked():
    analyzer = SegmentAnalyzer(minimum_regime_samples=10)
    rows = trades(30, regime="BULL") + trades(30, regime="BEAR", net_pnl=0.1)
    report = analyzer.by_regime(rows)
    assert set(report.reliable_cells) == {"BULL", "BEAR"}
    assert report.best == "BULL" and report.worst == "BEAR"


def test_a_profitable_strategy_can_still_be_losing_in_one_regime():
    """The reason the cut exists at all."""
    analyzer = SegmentAnalyzer(minimum_regime_samples=10)
    winners = trades(30, regime="BULL", net_pnl=2.0)
    losers = trades(30, regime="BEAR", net_pnl=1.0, alternate=False)
    for row in losers:
        row["net_pnl"] = -1.0
    report = analyzer.by_regime(winners + losers)
    assert report.cells["BULL"].net_pnl > 0
    assert report.cells["BEAR"].net_pnl < 0


def test_an_unlabelled_row_lands_in_an_unknown_cell_rather_than_being_dropped():
    rows = trades(5)
    for row in rows:
        row["regime"] = None
    report = SegmentAnalyzer().by_regime(rows)
    assert report.cells["UNKNOWN"].samples == 5


def test_execution_and_signal_timeframes_are_reported_separately():
    """Section 12: do not assume M5 is superior."""
    report = SegmentAnalyzer().all(trades(30, timeframe="M5", signal_timeframe="H1"))
    assert report["timeframe"]["cells"]["M5"]["samples"] == 30
    assert report["signal_timeframe"]["cells"]["H1"]["samples"] == 30
    assert "M5 is superior" in report["timeframe_note"]


def test_the_session_cut_reports_spread_and_slippage():
    analyzer = SegmentAnalyzer(minimum_session_samples=10)
    report = analyzer.by_session(trades(30, session="ASIA"))
    cell = report.cells["ASIA"]
    assert cell.spread == pytest.approx(0.00012)
    assert cell.slippage == pytest.approx(0.00005)
