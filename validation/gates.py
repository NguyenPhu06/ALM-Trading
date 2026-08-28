"""Performance gates and DEMO automation eligibility (sections 17 and 18).

A performance gate is a claim about evidence, not a switch. The decisive
property, stated in section 17 and enforced here: **a failed gate must not enable
higher-risk execution.** These objects can therefore only ever report; nothing in
this module writes a setting, releases a kill switch or arms a mode.

Section 18 works the same way. `DEMO_AUTOMATION_ELIGIBLE` is computed, and being
eligible changes nothing on its own — arming automation still requires
`DEMO_AUTOMATED_EXECUTION_ENABLED` and a named human.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from config.settings import load_yaml


class GateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class GateResult:
    name: str
    status: GateStatus
    observed: Any = None
    threshold: Any = None
    detail: str | None = None

    @property
    def passed(self) -> bool:
        return self.status is GateStatus.PASS

    def as_dict(self) -> dict[str, Any]:
        return {"gate": self.name, "status": str(self.status), "passed": self.passed,
                "observed": self.observed, "threshold": self.threshold,
                "detail": self.detail}


@dataclass(frozen=True, slots=True)
class PerformanceThresholds:
    """Section 17. Configurable, and deliberately demanding."""

    minimum_samples: int = 100
    maximum_drawdown: float = 0.05
    minimum_expectancy: float = 0.0
    minimum_profit_factor: float = 1.10
    maximum_rejection_rate: float = 0.10
    maximum_reconciliation_failure_rate: float = 0.0
    maximum_high_confidence_failure_rate: float = 0.30
    minimum_calibration_quality: float = 0.80

    @classmethod
    def from_config(cls, overrides: Mapping[str, Any] | None = None) -> "PerformanceThresholds":
        config = dict(load_yaml().get("phase_17", {}).get("gates", {}))
        config.update(dict(overrides or {}))
        known = {declared.name: declared.type for declared in fields(cls)}
        payload: dict[str, Any] = {}
        for name, value in config.items():
            if name in known:
                payload[name] = int(value) if known[name] == "int" else float(value)
        return cls(**payload)

    def as_dict(self) -> dict[str, Any]:
        return {declared.name: getattr(self, declared.name) for declared in fields(self)}


@dataclass(frozen=True, slots=True)
class PerformanceGateReport:
    passed: bool
    gates: tuple[GateResult, ...]
    failed: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    thresholds: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def enables_execution(self) -> bool:
        """Always False. Passing a gate is evidence, never an action."""
        return False

    def as_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "gates": [gate.as_dict() for gate in self.gates],
                "failed": list(self.failed), "unknown": list(self.unknown),
                "thresholds": dict(self.thresholds),
                "enables_execution": False,
                "note": "A passing gate is evidence. It never arms execution.",
                "timestamp": self.timestamp}


def _cmp(name: str, observed: Any, threshold: Any, *, at_least: bool) -> GateResult:
    """An unmeasured value is UNKNOWN, never a pass."""
    if observed is None:
        return GateResult(name, GateStatus.UNKNOWN, None, threshold, "NOT_MEASURED")
    value = float(observed)
    ok = value >= float(threshold) if at_least else value <= float(threshold)
    return GateResult(name, GateStatus.PASS if ok else GateStatus.FAIL, value, threshold)


class PerformanceGateEvaluator:
    """Reports which gates a body of evidence clears. It cannot change anything."""

    def __init__(self, thresholds: PerformanceThresholds | None = None):
        self.thresholds = thresholds or PerformanceThresholds.from_config()

    def evaluate(self, *, samples: int | None = None, drawdown: float | None = None,
                 expectancy: float | None = None, profit_factor: float | None = None,
                 rejection_rate: float | None = None,
                 reconciliation_failure_rate: float | None = None,
                 high_confidence_failure_rate: float | None = None,
                 calibration_quality: float | None = None) -> PerformanceGateReport:
        limits = self.thresholds
        gates = (
            _cmp("minimum_samples", samples, limits.minimum_samples, at_least=True),
            _cmp("maximum_drawdown", drawdown, limits.maximum_drawdown, at_least=False),
            _cmp("minimum_expectancy", expectancy, limits.minimum_expectancy, at_least=True),
            _cmp("minimum_profit_factor", profit_factor, limits.minimum_profit_factor,
                 at_least=True),
            _cmp("maximum_rejection_rate", rejection_rate, limits.maximum_rejection_rate,
                 at_least=False),
            _cmp("maximum_reconciliation_failure_rate", reconciliation_failure_rate,
                 limits.maximum_reconciliation_failure_rate, at_least=False),
            _cmp("maximum_high_confidence_failure_rate", high_confidence_failure_rate,
                 limits.maximum_high_confidence_failure_rate, at_least=False),
            _cmp("minimum_calibration_quality", calibration_quality,
                 limits.minimum_calibration_quality, at_least=True),
        )
        failed = tuple(gate.name for gate in gates if gate.status is GateStatus.FAIL)
        unknown = tuple(gate.name for gate in gates if gate.status is GateStatus.UNKNOWN)
        # Fail-closed: an unmeasured gate is not a passed gate.
        return PerformanceGateReport(not failed and not unknown, gates, failed, unknown,
                                     limits.as_dict())


# ------------------------------------------------------------------ section 18
ELIGIBILITY_CHECKS = (
    "champion_strategy", "sufficient_observations", "stable_model", "acceptable_drawdown",
    "execution_quality", "no_reconciliation_failures", "no_critical_data_issues",
    "kill_switch_released", "risk_gates_pass", "circuit_breaker_closed",
)


@dataclass(frozen=True, slots=True)
class AutomationEligibility:
    eligible: bool
    checks: dict[str, bool]
    missing: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    gate_report: PerformanceGateReport | None = None
    human_approved: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def enabled(self) -> bool:
        """Always False. Eligibility is a finding; arming is a configuration change."""
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "DEMO_AUTOMATION_ELIGIBLE": self.eligible,
            "checks": dict(self.checks), "missing": list(self.missing),
            "unknown": list(self.unknown), "human_approved": self.human_approved,
            "enabled": False, "automatically_enabled": False,
            "gate_report": self.gate_report.as_dict() if self.gate_report else None,
            "note": ("Eligibility never enables automation. DEMO_AUTOMATED still "
                     "requires DEMO_AUTOMATED_EXECUTION_ENABLED and a named human."),
            "timestamp": self.timestamp,
        }


class AutomationEligibilityEvaluator:
    """Computes DEMO_AUTOMATION_ELIGIBLE. It never sets a flag."""

    def __init__(self, settings: Any = None, *,
                 evaluator: PerformanceGateEvaluator | None = None):
        self.settings = settings
        self.gates = evaluator or PerformanceGateEvaluator()

    def evaluate(self, *, champion_strategy: bool | None = None,
                 observations: int | None = None, model_stable: bool | None = None,
                 drawdown: float | None = None, execution_quality: Any = None,
                 reconciliation_failures: int | None = None,
                 critical_data_issues: int | None = None,
                 kill_switch_engaged: bool | None = None,
                 risk_gates_pass: bool | None = None,
                 circuit_breaker_open: bool | None = None,
                 gate_report: PerformanceGateReport | None = None) -> AutomationEligibility:
        limits = self.gates.thresholds
        rejection = getattr(execution_quality, "rejection_rate", None)
        checks: dict[str, bool | None] = {
            "champion_strategy": champion_strategy,
            "sufficient_observations": (None if observations is None
                                        else observations >= limits.minimum_samples),
            "stable_model": model_stable,
            "acceptable_drawdown": (None if drawdown is None
                                    else drawdown <= limits.maximum_drawdown),
            "execution_quality": (None if rejection is None
                                  else rejection <= limits.maximum_rejection_rate),
            "no_reconciliation_failures": (None if reconciliation_failures is None
                                           else reconciliation_failures == 0),
            "no_critical_data_issues": (None if critical_data_issues is None
                                        else critical_data_issues == 0),
            "kill_switch_released": (None if kill_switch_engaged is None
                                     else not kill_switch_engaged),
            "risk_gates_pass": risk_gates_pass,
            "circuit_breaker_closed": (None if circuit_breaker_open is None
                                       else not circuit_breaker_open),
        }
        unknown = tuple(name for name, value in checks.items() if value is None)
        missing = tuple(name for name, value in checks.items() if value is False)
        if gate_report is not None and not gate_report.passed:
            missing = missing + ("performance_gates",)

        approved = bool(getattr(self.settings, "demo_automation_approved", False))
        # Fail-closed on every axis: unknown is not eligible.
        eligible = not missing and not unknown
        return AutomationEligibility(
            eligible=eligible,
            checks={name: bool(value) for name, value in checks.items() if value is not None},
            missing=missing, unknown=unknown, gate_report=gate_report,
            human_approved=approved)
