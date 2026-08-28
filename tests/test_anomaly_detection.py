"""Anomaly detection (section 21).

Nine change detectors. An anomaly says the system is behaving differently from
its own recent baseline — a reason to look, not a verdict that something is
wrong, and never a reason to change what the system does.
"""
import pytest

from validation.anomaly import NO_BASELINE, AnomalyDetector, AnomalyKind

BASELINE = {
    "signal_rate": 2.0, "spread": 0.00012, "slippage": 0.00005, "latency_ms": 40.0,
    "connection_failures": 0,
    "predictions": {"BUY": 50, "SELL": 50},
    "confidence_buckets": {"0.6": 50, "0.7": 50},
    "pnl_buckets": {"WIN": 55, "LOSS": 45},
    "regimes": {"BULL": 50, "BEAR": 50},
}


def detect(**overrides):
    current = dict(BASELINE)
    current.update(overrides)
    return AnomalyDetector().detect(current, BASELINE)


# ---------------------------------------------------------------- the baseline
def test_without_a_baseline_nothing_is_anomalous():
    """A first observation is not normal and not alarming; it is a first observation."""
    report = AnomalyDetector().detect(BASELINE, None)
    assert report.detected is False
    assert set(report.skipped) == {str(kind) for kind in AnomalyKind}
    assert report.checked == ()


def test_an_identical_window_is_not_anomalous():
    report = detect()
    assert report.detected is False
    assert len(report.checked) == len(AnomalyKind)


def test_a_missing_measurement_is_skipped_not_passed():
    report = detect(spread=None)
    assert str(AnomalyKind.ABNORMAL_SPREAD) in report.skipped
    assert str(AnomalyKind.ABNORMAL_SPREAD) not in report.checked


# ---------------------------------------------------------------- the detectors
@pytest.mark.parametrize("override,kind", [
    (dict(signal_rate=8.0), AnomalyKind.SIGNAL_FREQUENCY),
    (dict(spread=0.0010), AnomalyKind.ABNORMAL_SPREAD),
    (dict(slippage=0.0005), AnomalyKind.ABNORMAL_SLIPPAGE),
    (dict(latency_ms=400.0), AnomalyKind.EXECUTION_LATENCY),
    (dict(predictions={"BUY": 100, "SELL": 0}), AnomalyKind.PREDICTION_DISTRIBUTION),
    (dict(confidence_buckets={"0.9": 100}), AnomalyKind.CONFIDENCE_DISTRIBUTION),
    (dict(pnl_buckets={"WIN": 5, "LOSS": 95}), AnomalyKind.PNL_DISTRIBUTION),
    (dict(regimes={"BEAR": 100}), AnomalyKind.REGIME_DISTRIBUTION),
    (dict(connection_failures=4), AnomalyKind.MT5_CONNECTIVITY),
])
def test_each_declared_change_is_detected(override, kind):
    report = detect(**override)
    assert report.detected is True
    assert str(kind) in report.kinds


def test_a_small_change_is_not_an_anomaly():
    report = detect(signal_rate=2.2, spread=0.00013)
    assert report.detected is False


def test_a_quieter_feed_is_as_anomalous_as_a_busier_one():
    """Signals stopping is at least as interesting as signals surging."""
    assert str(AnomalyKind.SIGNAL_FREQUENCY) in detect(signal_rate=0.2).kinds


def test_fewer_connection_failures_is_not_an_anomaly():
    report = AnomalyDetector().detect({**BASELINE, "connection_failures": 0},
                                      {**BASELINE, "connection_failures": 5})
    assert str(AnomalyKind.MT5_CONNECTIVITY) not in report.kinds


def test_several_anomalies_are_reported_together():
    report = detect(spread=0.0010, latency_ms=400.0, regimes={"BEAR": 100})
    assert {str(AnomalyKind.ABNORMAL_SPREAD), str(AnomalyKind.EXECUTION_LATENCY),
            str(AnomalyKind.REGIME_DISTRIBUTION)} <= set(report.kinds)


def test_an_anomaly_reports_its_observed_and_baseline_values():
    report = detect(spread=0.0010)
    anomaly = next(row for row in report.anomalies
                   if row.kind is AnomalyKind.ABNORMAL_SPREAD)
    assert anomaly.observed == pytest.approx(0.0010)
    assert anomaly.baseline == pytest.approx(0.00012)
    assert anomaly.change > anomaly.threshold


# ------------------------------------------------------------------ profiling
def test_the_profile_reduces_a_population_to_a_comparable_shape():
    from tests.phase17_helpers import trades

    profile = AnomalyDetector.profile(trades(24), hours=24.0)
    assert profile["samples"] == 24
    assert profile["signal_rate"] == pytest.approx(1.0)
    assert profile["spread"] == pytest.approx(0.00012)
    assert set(profile["predictions"]) == {"BUY", "SELL"}
    assert set(profile["pnl_buckets"]) <= {"WIN", "LOSS", "FLAT"}


def test_the_signal_rate_is_per_hour_so_windows_are_comparable():
    from tests.phase17_helpers import trades

    day = AnomalyDetector.profile(trades(24), hours=24.0)
    week = AnomalyDetector.profile(trades(168), hours=168.0)
    assert day["signal_rate"] == pytest.approx(week["signal_rate"])


def test_a_profiled_window_can_be_compared_with_its_baseline():
    from tests.phase17_helpers import trades

    quiet = AnomalyDetector.profile(trades(24), hours=24.0)
    busy = AnomalyDetector.profile(trades(120), hours=24.0)
    report = AnomalyDetector().detect(busy, quiet)
    assert str(AnomalyKind.SIGNAL_FREQUENCY) in report.kinds


# --------------------------------------------------- detection changes nothing
def test_the_detector_cannot_change_the_system():
    for name in ("enable", "disable", "trip", "engage", "release", "apply"):
        assert not hasattr(AnomalyDetector, name)


def test_an_anomaly_does_not_trip_the_circuit_breaker():
    """Section 21 alerts; section 22 stops. They are different mechanisms."""
    from tests.phase17_helpers import breaker

    live = breaker()
    detect(spread=0.0010, latency_ms=400.0)
    assert live.open is False


def test_the_service_alerts_on_an_anomaly_without_acting(db_session):
    from database.models import DashboardAlertRecord
    from database.repositories import AlertRepository
    from database.repositories.validation import ValidationRepository
    from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter
    from tests.phase16_helpers import settings
    from tests.phase17_helpers import breaker
    from validation.service import ValidationService

    router = AlertRouter(AlertEngine(AlertRepositoryNotificationProvider(
        AlertRepository(db_session))))
    live = breaker()
    service = ValidationService(ValidationRepository(db_session), settings=settings(),
                                breaker=live, alerts=router)
    report = service.detect_anomalies({**BASELINE, "spread": 0.0010}, BASELINE)

    assert report.detected is True
    rows = db_session.query(DashboardAlertRecord).all()
    assert any(row.alert_type == "ANOMALY_DETECTED" for row in rows)
    assert live.open is False, "an alert is not a stop"
