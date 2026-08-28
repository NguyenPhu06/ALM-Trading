"""Execution, signal and model quality (sections 7, 8 and 9).

Three questions reported side by side, because a strategy with a positive
expectancy and a 40% rejection rate is not working, and a network that is
confidently wrong is more dangerous than one that knows it is guessing.
"""
import pytest

from database.models import ExecutionQualityRecord
from database.repositories.validation import ValidationRepository
from validation.quality import (
    calculate_execution_quality, calculate_model_quality, calculate_signal_quality,
)
from tests.phase17_helpers import execution_records, predictions, recorder, shadow_signal
from tests.phase17_helpers import EXIT_MOMENT


def quality(**kwargs):
    records = kwargs.pop("records", execution_records())
    return calculate_execution_quality(records, **kwargs)


# ------------------------------------------------------------------ section 7
def test_the_fill_and_rejection_rates_are_measured():
    result = quality(records=execution_records(20, rejected=4))
    assert result.submitted == 20 and result.filled == 16 and result.rejected == 4
    assert result.fill_rate == pytest.approx(0.80)
    assert result.rejection_rate == pytest.approx(0.20)


def test_a_partial_fill_counts_as_filled():
    records = execution_records(10)
    records[0]["status"] = "PARTIAL"
    result = quality(records=records)
    assert result.partially_filled == 1
    assert result.fill_rate == pytest.approx(1.0)


def test_errors_are_counted_separately_from_rejections():
    result = quality(records=execution_records(10, rejected=2, errored=3))
    assert result.rejected == 2 and result.errored == 3


def test_the_slippage_is_averaged_and_its_worst_case_kept():
    records = execution_records(5, slippage=0.0001)
    records[0]["slippage"] = 0.0009
    result = quality(records=records)
    assert result.worst_slippage == pytest.approx(0.0009)
    assert result.average_slippage == pytest.approx((0.0009 + 0.0001 * 4) / 5)


def test_the_spread_distribution_reports_percentiles():
    records = execution_records(10)
    for index, row in enumerate(records):
        row["spread"] = 0.0001 * (index + 1)
    result = quality(records=records)
    assert result.spread_distribution["min"] == pytest.approx(0.0001)
    assert result.spread_distribution["max"] == pytest.approx(0.0010)
    assert result.spread_distribution["p50"] is not None


def test_latency_is_reported_as_a_distribution():
    result = quality(records=execution_records(40, latency_ms=42.0))
    assert result.latency_ms["p50"] == pytest.approx(42.0)


def test_an_unmeasured_latency_is_not_a_fast_one():
    records = [{"status": "FILLED"} for _ in range(5)]
    result = quality(records=records)
    assert result.latency_ms["p50"] is None
    assert result.average_slippage is None


def test_reconciliation_and_connection_failures_are_carried_through():
    result = quality(reconciliation_failures=2, connection_failures=3)
    assert result.reconciliation_failures == 2 and result.connection_failures == 3


def test_a_small_sample_is_not_reliable():
    result = quality(records=execution_records(5))
    assert result.reliable is False and "INSUFFICIENT_SAMPLES" in result.reasons


def test_a_large_enough_sample_is_reliable():
    assert quality(records=execution_records(40)).reliable is True


def test_an_empty_population_reports_nothing_rather_than_zero_rates():
    result = quality(records=[])
    assert result.submitted == 0 and result.fill_rate is None
    assert result.rejection_rate is None and result.reliable is False


# ------------------------------------------------------------------ section 8
def test_signal_counts_split_by_side():
    live = recorder()
    from tests.phase16_helpers import order

    shadow_signal(recorder_=live)
    shadow_signal(request=order(side="SELL", signal_id="s2", stop_loss=1.11, take_profit=1.09),
                  recorder_=live)
    result = calculate_signal_quality(live.signals, ())
    assert result.signals == 2 and result.buy == 1 and result.sell == 1


def test_unresolved_signals_are_not_counted_as_flat():
    live = recorder()
    shadow_signal(recorder_=live)
    result = calculate_signal_quality(live.signals, ())
    assert result.signals == 1 and result.resolved == 0
    assert result.win_rate is None and result.expectancy is None


def test_signal_performance_comes_from_resolved_outcomes():
    from types import SimpleNamespace

    outcomes = [SimpleNamespace(net_expected_pnl=value, mae=-0.001, mfe=0.002)
                for value in (1.0, 1.0, -0.5)]
    result = calculate_signal_quality((), outcomes)
    assert result.resolved == 3 and result.wins == 2 and result.losses == 1
    assert result.win_rate == pytest.approx(2 / 3, abs=1e-4)
    assert result.profit_factor == pytest.approx(4.0)
    assert result.net_pnl == pytest.approx(1.5)


def test_signal_quality_needs_a_sample_before_it_is_reliable():
    from types import SimpleNamespace

    outcomes = [SimpleNamespace(net_expected_pnl=1.0, mae=0.0, mfe=0.0) for _ in range(5)]
    assert calculate_signal_quality((), outcomes).reliable is False


# ------------------------------------------------------------------ section 9
def test_model_accuracy_and_calibration_are_measured():
    result = calculate_model_quality(predictions(40, accuracy=0.6, confidence=0.7))
    assert result.samples == 40
    assert result.accuracy == pytest.approx(0.6)
    assert result.mean_confidence == pytest.approx(0.7)
    assert result.calibration_gap == pytest.approx(0.1)


def test_a_perfectly_calibrated_model_scores_one():
    result = calculate_model_quality(predictions(40, accuracy=0.7, confidence=0.7))
    assert result.calibration_gap == pytest.approx(0.0)
    assert result.calibration_quality == pytest.approx(1.0)


def test_overconfidence_is_flagged():
    result = calculate_model_quality(predictions(40, accuracy=0.4, confidence=0.9))
    assert result.calibration_gap > 0.2
    assert "OVERCONFIDENT" in result.reasons


def test_high_confidence_failures_are_counted_separately():
    """A model that is wrong while sure is more dangerous than one that is unsure."""
    result = calculate_model_quality(predictions(40, accuracy=0.5, confidence=0.9))
    assert result.high_confidence_failures == 20
    assert result.high_confidence_failure_rate == pytest.approx(0.5)


def test_low_confidence_errors_are_not_high_confidence_failures():
    result = calculate_model_quality(predictions(40, accuracy=0.5, confidence=0.5))
    assert result.high_confidence_failures == 0
    assert result.high_confidence_failure_rate is None


def test_false_directions_are_counted():
    rows = ([{"predicted": "UP", "actual": "DOWN", "confidence": 0.7}] * 3
            + [{"predicted": "DOWN", "actual": "UP", "confidence": 0.7}] * 2
            + [{"predicted": "NEUTRAL", "actual": "UP", "confidence": 0.7}])
    result = calculate_model_quality(rows)
    assert result.false_bullish == 3 and result.false_bearish == 2
    assert result.false_neutral == 1


def test_an_unscored_prediction_is_excluded_not_counted_correct():
    rows = predictions(10) + [{"predicted": "UP", "actual": None, "confidence": 0.7}]
    assert calculate_model_quality(rows).samples == 10


def test_no_scored_predictions_reports_nothing():
    result = calculate_model_quality([])
    assert result.samples == 0 and result.accuracy is None
    assert "NO_SCORED_PREDICTIONS" in result.reasons


def test_prediction_drift_compares_against_a_baseline():
    current = [{"predicted": "UP", "actual": "UP", "confidence": 0.8}] * 40
    baseline = [{"predicted": "DOWN", "actual": "DOWN", "confidence": 0.5}] * 40
    result = calculate_model_quality(current, baseline=baseline)
    assert result.prediction_drift == pytest.approx(1.0)
    assert result.confidence_drift == pytest.approx(0.3)
    assert result.model_drift is True


def test_without_a_baseline_there_is_no_drift_claim():
    result = calculate_model_quality(predictions(40))
    assert result.prediction_drift is None and result.model_drift is False


# --------------------------------------------------------------- persistence
def test_execution_quality_persists(db_session):
    repository = ValidationRepository(db_session)
    repository.save_execution_quality(quality(records=execution_records(40, rejected=4)),
                                      window="30d")
    row = db_session.query(ExecutionQualityRecord).one()
    assert row.window == "30d" and row.submitted == 40 and row.rejected == 4
    assert row.rejection_rate == pytest.approx(0.1)
