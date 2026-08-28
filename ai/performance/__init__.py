"""Forward performance: model memory, rolling metrics, error and segment analysis."""
from ai.performance.errors import ErrorAnalysis, ErrorAnalyzer, ErrorClass
from ai.performance.memory import (
    CAUSALITY_DISCLAIMER,
    TRACKED_GROUPS,
    ModelMemory,
    ModelPerformanceEntry,
    group_importance,
)
from ai.performance.rolling import (
    WINDOWS,
    PerformanceEntry,
    RollingMetrics,
    RollingPerformance,
    calibration_report,
)
from ai.performance.segments import (
    REGIME_SEGMENTS,
    SESSION_SEGMENTS,
    TIMEFRAME_SEGMENTS,
    ForwardSegmentLearner,
    SegmentLearning,
    SegmentLearningReport,
    SegmentVerdict,
)

__all__ = [
    "ErrorAnalyzer", "ErrorAnalysis", "ErrorClass",
    "ModelMemory", "ModelPerformanceEntry", "group_importance", "CAUSALITY_DISCLAIMER",
    "TRACKED_GROUPS",
    "RollingPerformance", "RollingMetrics", "PerformanceEntry", "calibration_report",
    "WINDOWS",
    "ForwardSegmentLearner", "SegmentLearning", "SegmentLearningReport", "SegmentVerdict",
    "REGIME_SEGMENTS", "SESSION_SEGMENTS", "TIMEFRAME_SEGMENTS",
]
