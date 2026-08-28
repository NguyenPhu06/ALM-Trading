"""Performance gates (section 17).

The decisive property, stated in the spec and enforced here: **a failed gate must
not enable higher-risk execution.** These objects can only report. An unmeasured
gate is UNKNOWN, which is not a pass.
"""
import pytest

from database.models import PerformanceGateRecord
from database.repositories.validation import ValidationRepository
from validation.gates import (
    GateStatus, PerformanceGateEvaluator, PerformanceThresholds,
)

CLEAN = dict(samples=200, drawdown=0.01, expectancy=0.0005, profit_factor=1.5,
             rejection_rate=0.02, reconciliation_failure_rate=0.0,
             high_confidence_failure_rate=0.10, calibration_quality=0.90)


def evaluate(**overrides):
    payload = dict(CLEAN)
    payload.update(overrides)
    return PerformanceGateEvaluator().evaluate(**payload)


# ------------------------------------------------------------- the thresholds
def test_the_shipped_thresholds_are_demanding():
    limits = PerformanceThresholds.from_config()
    assert limits.minimum_samples >= 100
    assert limits.maximum_drawdown <= 0.10
    assert limits.minimum_profit_factor >= 1.0
    assert limits.maximum_reconciliation_failure_rate == 0.0


def test_every_threshold_is_configurable():
    limits = PerformanceThresholds.from_config({"minimum_samples": 7})
    assert limits.minimum_samples == 7


def test_all_eight_declared_gates_are_evaluated():
    names = {gate.name for gate in evaluate().gates}
    assert names == {"minimum_samples", "maximum_drawdown", "minimum_expectancy",
                     "minimum_profit_factor", "maximum_rejection_rate",
                     "maximum_reconciliation_failure_rate",
                     "maximum_high_confidence_failure_rate", "minimum_calibration_quality"}


# ---------------------------------------------------------------- the verdicts
def test_clean_evidence_passes_every_gate():
    report = evaluate()
    assert report.passed is True and report.failed == () and report.unknown == ()


@pytest.mark.parametrize("override,gate", [
    (dict(samples=5), "minimum_samples"),
    (dict(drawdown=0.50), "maximum_drawdown"),
    (dict(expectancy=-0.001), "minimum_expectancy"),
    (dict(profit_factor=0.5), "minimum_profit_factor"),
    (dict(rejection_rate=0.90), "maximum_rejection_rate"),
    (dict(reconciliation_failure_rate=0.10), "maximum_reconciliation_failure_rate"),
    (dict(high_confidence_failure_rate=0.90), "maximum_high_confidence_failure_rate"),
    (dict(calibration_quality=0.10), "minimum_calibration_quality"),
])
def test_each_gate_can_fail_on_its_own(override, gate):
    report = evaluate(**override)
    assert report.passed is False and gate in report.failed


def test_an_unmeasured_gate_is_unknown_not_a_pass():
    """Fail-closed: not measuring something is not evidence that it is fine."""
    report = evaluate(calibration_quality=None)
    assert report.passed is False
    assert "minimum_calibration_quality" in report.unknown
    assert "minimum_calibration_quality" not in report.failed


def test_an_unknown_gate_reports_why():
    report = evaluate(drawdown=None)
    gate = next(row for row in report.gates if row.name == "maximum_drawdown")
    assert gate.status is GateStatus.UNKNOWN and gate.detail == "NOT_MEASURED"


def test_several_failures_are_all_reported():
    report = evaluate(samples=5, drawdown=0.50, profit_factor=0.5)
    assert {"minimum_samples", "maximum_drawdown", "minimum_profit_factor"} <= set(report.failed)


def test_a_gate_at_its_threshold_passes():
    limits = PerformanceThresholds.from_config()
    report = evaluate(drawdown=limits.maximum_drawdown,
                      profit_factor=limits.minimum_profit_factor,
                      samples=limits.minimum_samples)
    assert report.passed is True


# ---------------------------------------------------- gates never enable anything
def test_a_passing_report_still_enables_nothing():
    report = evaluate()
    assert report.passed is True
    assert report.enables_execution is False
    assert report.as_dict()["enables_execution"] is False


def test_a_failing_report_enables_nothing_either():
    assert evaluate(samples=1).enables_execution is False


def test_the_evaluator_has_no_way_to_change_a_setting():
    for name in ("enable", "arm", "apply", "settings", "release", "engage"):
        assert not hasattr(PerformanceGateEvaluator, name)


def test_a_failed_gate_does_not_raise_a_higher_risk_mode(db_session):
    """Section 17, end to end: a gate report cannot move the system."""
    from tests.phase16_helpers import service_for, settings

    service, _ = service_for(db_session, settings())
    before = service.status()["execution_mode"]
    evaluate(samples=1)
    assert service.status()["execution_mode"] == before == "OBSERVATION"


# ---------------------------------------------------------------- persistence
def test_a_gate_report_persists_one_row_per_gate(db_session):
    repository = ValidationRepository(db_session)
    repository.save_gate_report(evaluate(samples=5))
    rows = db_session.query(PerformanceGateRecord).all()
    assert len(rows) == 8
    failed = [row for row in rows if row.status == "FAIL"]
    assert failed and failed[0].gate == "minimum_samples"


def test_a_persisted_gate_never_records_enabling_execution(db_session):
    repository = ValidationRepository(db_session)
    repository.save_gate_report(evaluate())
    rows = db_session.query(PerformanceGateRecord).all()
    assert all(row.enabled_execution is False for row in rows)
