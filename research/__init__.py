"""AI research lab: compare strategies, features and models on forward evidence.

Nothing in this package executes. No module imports an execution client, holds a
broker handle, or changes a setting — research reads recorded observations and
produces reports. That is asserted structurally by `tests/test_phase15_safety.py`,
which parses every module in the package.

The lab's default answers are deliberately negative: a component does not
improve the strategy, the NN's value is not proven, DCA does not help, and there
is no edge. Each has to be demonstrated against forward observations before the
verdict changes.
"""
from research.ablation import (
    ABLATION_ARMS,
    COMPONENT_ARMS,
    AblationReport,
    AblationStudy,
    ArmResult,
    ComponentVerdict,
)
from research.champion import (
    GATES,
    ChallengerReport,
    ChallengerVerdict,
    Gate,
    StrategyChallengerEvaluator,
    rejection_criteria,
)
from research.conflicts import (
    SIGNALS,
    Conflict,
    ConflictEngine,
    ConflictType,
    Resolution,
    Severity,
)
from research.dca import DCA_ARMS, DCAReport, DCAResearch, DCAVerdict
from research.error_lab import REPORTS, ErrorLab, ErrorReport
from research.exits import EXIT_KINDS, ExitReport, ExitResearch, ExitVerdict
from research.experiments import (
    CATALOGUE,
    FEATURE_FAMILIES,
    ExperimentConfig,
    ExperimentResult,
    ExperimentRunner,
    ExperimentSpec,
    catalogue,
    compare,
    configured,
)
from research.holdout import HoldoutGuard, HoldoutSplit, HoldoutViolation
from research.liquidity_events import (
    EVENT_TYPES,
    EventStudyReport,
    LiquidityEventStudy,
)
from research.matrices import ACTIVE_SESSIONS, Matrix, MatrixBuilder, MatrixCell
from research.metrics import PerformanceMetrics, delta, evaluate
from research.models import (
    REGIMES,
    SESSIONS,
    TIMEFRAMES,
    ResearchObservation,
    require_forward_only,
    segment,
)
from research.multiple_testing import (
    ExperimentLedger,
    MultipleTestingReport,
    SelectionMethod,
)
from research.nn_value import NNValueReport, NNValueTest, NNValueVerdict
from research.registry import (
    ApprovalToken,
    PromotionRefused,
    StrategyRecord,
    StrategyRegistry,
    StrategyStatus,
    TransitionRefused,
    strategy,
)
from research.reports import REPORT_FILES, ReportBundle, ResearchReporter
from research.significance import (
    SignificanceReport,
    SignificanceTester,
    SignificanceVerdict,
    effect_size,
)
from research.weights import SignalWeightResearch, WeightProposal

__all__ = [
    # observations and metrics
    "ResearchObservation", "require_forward_only", "segment", "REGIMES", "SESSIONS",
    "TIMEFRAMES", "PerformanceMetrics", "evaluate", "delta",
    # registry
    "StrategyRegistry", "StrategyRecord", "StrategyStatus", "ApprovalToken",
    "TransitionRefused", "PromotionRefused", "strategy",
    # experiments
    "ExperimentConfig", "ExperimentSpec", "ExperimentResult", "ExperimentRunner",
    "CATALOGUE", "FEATURE_FAMILIES", "catalogue", "configured", "compare",
    # studies
    "AblationStudy", "AblationReport", "ArmResult", "ComponentVerdict", "ABLATION_ARMS",
    "COMPONENT_ARMS", "MatrixBuilder", "Matrix", "MatrixCell", "ACTIVE_SESSIONS",
    "DCAResearch", "DCAReport", "DCAVerdict", "DCA_ARMS",
    "ExitResearch", "ExitReport", "ExitVerdict", "EXIT_KINDS",
    "NNValueTest", "NNValueReport", "NNValueVerdict",
    "LiquidityEventStudy", "EventStudyReport", "EVENT_TYPES",
    "ConflictEngine", "Conflict", "ConflictType", "Severity", "Resolution", "SIGNALS",
    "SignalWeightResearch", "WeightProposal",
    "ErrorLab", "ErrorReport", "REPORTS",
    # champion / challenger
    "StrategyChallengerEvaluator", "ChallengerReport", "ChallengerVerdict", "Gate",
    "GATES", "rejection_criteria",
    # rigour
    "SignificanceTester", "SignificanceReport", "SignificanceVerdict", "effect_size",
    "ExperimentLedger", "MultipleTestingReport", "SelectionMethod",
    "HoldoutGuard", "HoldoutSplit", "HoldoutViolation",
    # reporting
    "ResearchReporter", "ReportBundle", "REPORT_FILES",
]
