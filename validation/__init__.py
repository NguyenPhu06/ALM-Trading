"""Phase 17 — DEMO validation and shadow trading.

This package measures. It holds no execution client, no guard and no transport,
and nothing in it can place, modify or cancel an order. Its job is to answer one
question honestly: does the current Champion Strategy and Neural Network produce
stable forward performance **after real execution costs**?

SHADOW is not a second pipeline. A shadow record is minted from the same
`GateChainDecision` the DEMO path produced, so the two cannot drift apart:
same market data, features, inference, strategy decision, risk evaluation and
execution proposal — the difference is the broker call, which SHADOW never makes.

The defaults here are all negative. No edge, DCA not proven, even-hour policy not
proven, automation not eligible. Each has to be demonstrated on a sample large
enough to mean something, and `INSUFFICIENT_DATA` is the expected answer for a
long time.
"""
from validation.anomaly import Anomaly, AnomalyDetector, AnomalyKind, AnomalyReport, NO_BASELINE
from validation.circuit_breaker import (
    CIRCUIT_BREAKER_OPEN, POSITIONS_UNTOUCHED, RECOVERY_CHECKS, BreakerEvent, BreakerSignals,
    BreakerState, BreakerTrigger, CircuitBreaker, RecoveryChecklist, RecoveryRefused,
)
from validation.comparison import (
    DemoOutcomeView, DifferenceKind, ShadowDemoComparator, ShadowDemoComparison,
)
from validation.dca_validation import (
    DCAArm, DCALevelStats, DCAValidationReport, DCAValidator, DCAVerdict,
)
from validation.even_hour import (
    REQUIRED_OBSERVATIONS, CheckpointRecord, EvenHourReport, EvenHourValidator, EvenHourVerdict,
)
from validation.gates import (
    ELIGIBILITY_CHECKS, AutomationEligibility, AutomationEligibilityEvaluator, GateResult,
    GateStatus, PerformanceGateEvaluator, PerformanceGateReport, PerformanceThresholds,
)
from validation.quality import (
    ExecutionQuality, ModelQuality, SignalQuality, calculate_execution_quality,
    calculate_model_quality, calculate_signal_quality,
)
from validation.reviews import DailyReview, ReviewBuilder, WeeklyReview
from validation.service import ValidationService
from validation.segments import (
    REGIMES, SESSIONS, TIMEFRAMES, SegmentAnalyzer, SegmentPerformance, SegmentReport,
)
from validation.shadow import (
    NOT_EXECUTED_BLOCKED, NOT_EXECUTED_MODE, NOT_EXECUTED_PENDING, SHADOW_SOURCE,
    ShadowOutcome, ShadowRecorder, ShadowSignal, ShadowStatus, shadow_signal_id,
)
from validation.windows import (
    WINDOWS, EdgeStatus, RollingWindowEvaluator, SampleRequirements, WindowPerformance,
)

__all__ = [
    "Anomaly", "AnomalyDetector", "AnomalyKind", "AnomalyReport", "AutomationEligibility",
    "AutomationEligibilityEvaluator", "BreakerEvent", "BreakerSignals", "BreakerState",
    "BreakerTrigger", "CIRCUIT_BREAKER_OPEN", "CheckpointRecord", "CircuitBreaker",
    "DCAArm", "DCALevelStats", "DCAValidationReport", "DCAValidator", "DCAVerdict",
    "DailyReview", "DemoOutcomeView", "DifferenceKind", "ELIGIBILITY_CHECKS", "EdgeStatus",
    "EvenHourReport", "EvenHourValidator", "EvenHourVerdict", "ExecutionQuality",
    "GateResult", "GateStatus", "ModelQuality", "NOT_EXECUTED_BLOCKED", "NOT_EXECUTED_MODE",
    "NOT_EXECUTED_PENDING", "NO_BASELINE", "POSITIONS_UNTOUCHED", "PerformanceGateEvaluator",
    "PerformanceGateReport", "PerformanceThresholds", "RECOVERY_CHECKS", "REGIMES",
    "REQUIRED_OBSERVATIONS", "RecoveryChecklist", "RecoveryRefused", "ReviewBuilder",
    "RollingWindowEvaluator", "SESSIONS", "SHADOW_SOURCE", "SampleRequirements",
    "SegmentAnalyzer", "SegmentPerformance", "SegmentReport", "ShadowDemoComparator",
    "ValidationService",
    "ShadowDemoComparison", "ShadowOutcome", "ShadowRecorder", "ShadowSignal",
    "ShadowStatus", "SignalQuality", "TIMEFRAMES", "WINDOWS", "WeeklyReview",
    "WindowPerformance", "calculate_execution_quality", "calculate_model_quality",
    "calculate_signal_quality", "shadow_signal_id",
]
