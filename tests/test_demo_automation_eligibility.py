"""DEMO automation eligibility (section 18).

`DEMO_AUTOMATION_ELIGIBLE` is computed and advisory. The whole point of this file
is that computing it changes nothing: being eligible does not arm automation, and
a human is still required.
"""
import pytest
from pydantic import ValidationError

from config.settings import Settings
from execution.demo.modes import ExecutionMode
from validation.gates import (
    ELIGIBILITY_CHECKS, AutomationEligibilityEvaluator, PerformanceGateEvaluator,
)
from tests.phase16_helpers import BASE, armed, settings
from tests.phase17_helpers import breaker

ELIGIBLE = dict(champion_strategy=True, observations=200, model_stable=True, drawdown=0.01,
                reconciliation_failures=0, critical_data_issues=0,
                kill_switch_engaged=False, risk_gates_pass=True, circuit_breaker_open=False)


class Quality:
    def __init__(self, rejection_rate=0.02):
        self.rejection_rate = rejection_rate


def evaluate(config=None, **overrides):
    payload = dict(ELIGIBLE)
    payload.setdefault("execution_quality", Quality())
    payload.update(overrides)
    return AutomationEligibilityEvaluator(config or armed()).evaluate(**payload)


# ------------------------------------------------------------- the checks
def test_all_ten_declared_checks_are_evaluated():
    result = evaluate()
    assert set(result.checks) == set(ELIGIBILITY_CHECKS)


def test_a_complete_and_healthy_picture_is_eligible():
    assert evaluate().eligible is True


@pytest.mark.parametrize("override,check", [
    (dict(champion_strategy=False), "champion_strategy"),
    (dict(observations=5), "sufficient_observations"),
    (dict(model_stable=False), "stable_model"),
    (dict(drawdown=0.90), "acceptable_drawdown"),
    (dict(execution_quality=Quality(0.90)), "execution_quality"),
    (dict(reconciliation_failures=1), "no_reconciliation_failures"),
    (dict(critical_data_issues=1), "no_critical_data_issues"),
    (dict(kill_switch_engaged=True), "kill_switch_released"),
    (dict(risk_gates_pass=False), "risk_gates_pass"),
    (dict(circuit_breaker_open=True), "circuit_breaker_closed"),
])
def test_each_requirement_can_block_eligibility(override, check):
    result = evaluate(**override)
    assert result.eligible is False and check in result.missing


def test_an_unknown_check_blocks_rather_than_passes():
    """Fail-closed on every axis: unknown is not eligible."""
    result = evaluate(model_stable=None)
    assert result.eligible is False
    assert "stable_model" in result.unknown
    assert "stable_model" not in result.missing


def test_a_failed_performance_gate_blocks_eligibility():
    failing = PerformanceGateEvaluator().evaluate(samples=1)
    result = evaluate(gate_report=failing)
    assert result.eligible is False and "performance_gates" in result.missing


def test_a_passing_performance_gate_does_not_block():
    passing = PerformanceGateEvaluator().evaluate(
        samples=200, drawdown=0.01, expectancy=0.0005, profit_factor=1.5,
        rejection_rate=0.02, reconciliation_failure_rate=0.0,
        high_confidence_failure_rate=0.10, calibration_quality=0.90)
    assert evaluate(gate_report=passing).eligible is True


# -------------------------------------------------- eligibility enables nothing
def test_eligibility_never_reports_itself_enabled():
    result = evaluate()
    assert result.eligible is True
    assert result.enabled is False
    assert result.as_dict()["automatically_enabled"] is False


def test_the_evaluator_cannot_change_a_setting():
    for name in ("enable", "arm", "apply", "promote", "release"):
        assert not hasattr(AutomationEligibilityEvaluator, name)


def test_being_eligible_does_not_arm_automation():
    """The shipped configuration is unchanged by an eligible verdict."""
    config = settings()
    result = AutomationEligibilityEvaluator(config).evaluate(**ELIGIBLE,
                                                             execution_quality=Quality())
    assert result.eligible is True
    assert config.demo_automated_execution_enabled is False
    assert config.execution_mode == "OBSERVATION"


def test_human_approval_is_reported_separately_from_eligibility():
    approved = AutomationEligibilityEvaluator(
        settings(demo_automation_approved=True)).evaluate(
            **ELIGIBLE, execution_quality=Quality())
    assert approved.human_approved is True
    assert approved.enabled is False, "approval is not arming"


def test_approval_alone_does_not_arm_automated_execution():
    """Section 18: DEMO_AUTOMATED still needs its own opt-in."""
    with pytest.raises(ValidationError, match="DEMO_AUTOMATED_EXECUTION_ENABLED"):
        Settings(**BASE, demo_execution_mode="DEMO_AUTOMATED", demo_trading_enabled=True,
                 mt5_execution_enabled=True, execution_kill_switch=False,
                 demo_automation_approved=True)


def test_the_shipped_default_is_not_approved():
    assert Settings(**BASE).demo_automation_approved is False


# ------------------------------------------------------------- the breaker link
def test_an_open_breaker_makes_the_system_ineligible():
    from validation.circuit_breaker import BreakerTrigger

    live = breaker()
    live.trip([BreakerTrigger.DAILY_LOSS_EXCEEDED])
    result = evaluate(circuit_breaker_open=live.open)
    assert result.eligible is False and "circuit_breaker_closed" in result.missing


def test_the_service_reports_eligibility_without_changing_anything(db_session):
    from database.repositories.validation import ValidationRepository
    from validation.service import ValidationService

    config = settings()
    service = ValidationService(ValidationRepository(db_session), settings=config,
                                breaker=breaker())
    result = service.automation_eligibility(**ELIGIBLE, execution_quality=Quality())
    assert result.eligible is True and result.enabled is False
    assert config.execution_mode == "OBSERVATION"
