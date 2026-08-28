"""Phases 12 and 14: live market validation, observation mode, and the 24/7 loop.

Nothing in this package sends an order. The terminal stage of every cycle is
`ExecutionSimulator`, which has no transport of any kind, and the Phase 14 driver
that schedules those cycles holds no execution client either.
"""
from observation.cycle import CycleStage, ObservationCycle, ObservationResult
from observation.driver import (
    ALLOWED_INTERVALS, CycleReport, DriverConfig, DriverState, DriverTick,
    ObservationDriver, TickOutcome, candle_timestamp, deterministic_cycle_id,
)
from observation.ingestion import DatasetIngestor, IngestionRefusal, IngestionResult
from observation.lifecycle import (
    FAILURE_STATES, LifecycleError, Observation, ObservationStatus,
    deterministic_observation_id, observation_from_cycle,
)
from observation.outcome import (
    ExecutionCosts, ForwardOutcome, ForwardOutcomeEngine, OutcomeRefusal, OutcomeResult,
)
from observation.dca_analysis import DCAAnalyzer, DCALevel, DCAProjection
from observation.demo_account import (
    DemoAccountResult, DemoAccountValidator, DemoValidation,
)
from observation.health import (
    COMPONENTS, ComponentHealth, ComponentStatus, SystemHealth, SystemHealthMonitor,
)
from observation.liquidity_evidence import (
    Confidence, EvidenceKind, LiquidityEvidence, LiquidityEvidenceClassifier, LiquidityReport,
    contains_forbidden_claim,
)
from observation.quality_gate import DataQualityGate, GateResult, GateVerdict
from observation.regime import (
    MarketRegime, MarketRegimeEngine, RegimeResult, TimeframeEvidence,
)
from observation.simulation import (
    ExecutionSimulation, ExecutionSimulator, ExecutionVerdict, RiskVerdict, SignalAction,
)
from observation.snapshot import FeatureSnapshot, MarketSnapshot, jsonable, new_cycle_id
from observation.time_exit import ExitDecision, TimeExitAnalysis, TimeExitAnalyzer, TrendAlignment

__all__ = [
    "COMPONENTS", "ComponentHealth", "ComponentStatus", "Confidence", "CycleStage",
    "DCAAnalyzer", "DCALevel", "DCAProjection", "DataQualityGate", "DemoAccountResult",
    "DemoAccountValidator", "DemoValidation", "EvidenceKind", "ExecutionSimulation",
    "ExecutionSimulator", "ExecutionVerdict", "ExitDecision", "FeatureSnapshot",
    "GateResult", "GateVerdict", "LiquidityEvidence", "LiquidityEvidenceClassifier",
    "LiquidityReport", "MarketRegime", "MarketRegimeEngine", "MarketSnapshot",
    "ObservationCycle", "ObservationResult", "RegimeResult", "RiskVerdict", "SignalAction",
    "SystemHealth", "SystemHealthMonitor", "TimeExitAnalysis", "TimeExitAnalyzer",
    "TimeframeEvidence", "TrendAlignment", "contains_forbidden_claim", "jsonable",
    "new_cycle_id",
    # Phase 14
    "ObservationDriver", "DriverConfig", "DriverState", "DriverTick", "CycleReport",
    "TickOutcome", "ALLOWED_INTERVALS", "candle_timestamp", "deterministic_cycle_id",
    "Observation", "ObservationStatus", "FAILURE_STATES", "LifecycleError",
    "observation_from_cycle", "deterministic_observation_id",
    "ForwardOutcomeEngine", "ForwardOutcome", "OutcomeResult", "OutcomeRefusal",
    "ExecutionCosts", "DatasetIngestor", "IngestionResult", "IngestionRefusal",
]
