"""Phase 16 — controlled MT5 DEMO trading.

LIVE trading is impossible here and always will be. This package adds a gated,
DEMO-only execution path on top of the Phase 11 foundation so that the full
decision -> risk -> execution -> reconciliation -> learning lifecycle can be
validated against real broker execution.

The default posture is OBSERVATION: nothing in this package sends an order until
someone deliberately configures a broker mode, opens every flag, releases the
kill switch, and connects a verified DEMO account.
"""
from execution.demo.approval import (
    PROPOSAL_BLOCKED, PROPOSAL_EXPIRED, PROPOSAL_NOT_FOUND, PROPOSAL_NOT_PENDING,
    ApprovalRefused, ExecutionProposal, ManualApprovalQueue,
)
from execution.demo.comparison import (
    EXECUTION_ERROR, MODEL_ERROR, RISK_REJECTION, SIGNAL_QUALITY_ERROR, SLIPPAGE_ERROR,
    SPREAD_ERROR, STRATEGY_ERROR, ExecutionAttribution, ExecutionComparator,
    PaperDemoComparison,
)
from execution.demo.daily_risk import DailyRiskState, DailyRiskTracker
from execution.demo.emergency import (
    EmergencyController, EmergencyDecision, EmergencySignals, EmergencyTrigger,
    POSITIONS_UNTOUCHED, SHUTDOWN_ACTION,
)
from execution.demo.exit_engine import DemoExitEngine, ExitAction, ExitReason, ExitVerdict
from execution.demo.feedback import DemoFeedbackPublisher, DemoTradeFeedback
from execution.demo.gates import (
    GATE_ORDER, DemoExecutionContext, DemoGateChain, GateChainDecision, GateOutcome,
)
from execution.demo.idempotency import (
    DUPLICATE_EXECUTION_REQUEST, IdempotencyRegistry, IdempotencyVerdict,
)
from execution.demo.journal import DemoTradeJournal, DemoTradeJournalEntry
from execution.demo.limits import DemoRiskLimits
from execution.demo.modes import (
    BROKER_MODES, DEFAULT_MODE, SIMULATION_MODES, ExecutionMode, ExecutionModeResolver,
    ModeDecision, UnknownExecutionMode, parse_mode,
)
from execution.demo.monitor import PositionMonitor, PositionSnapshot
from execution.demo.order import DemoOrderRequest, execution_request_id
from execution.demo.performance import DemoPerformance, calculate_demo_performance
from execution.demo.service import ControlledDemoTradingService, DemoExecutionOutcome
from execution.demo.sizing import PositionSize, PositionSizer, SymbolContract
from execution.demo.states import (
    ALLOWED_TRANSITIONS, TERMINAL_STATES, DemoExecutionState, ExecutionLifecycle,
    ExecutionStateError, StateTransition, state_for_result,
)

__all__ = [
    "ALLOWED_TRANSITIONS", "ApprovalRefused", "BROKER_MODES", "ControlledDemoTradingService",
    "DEFAULT_MODE", "DUPLICATE_EXECUTION_REQUEST", "DailyRiskState", "DailyRiskTracker",
    "DemoExecutionContext", "DemoExecutionOutcome", "DemoExecutionState", "DemoExitEngine",
    "DemoFeedbackPublisher", "DemoGateChain", "DemoOrderRequest", "DemoPerformance",
    "DemoRiskLimits", "DemoTradeFeedback", "DemoTradeJournal", "DemoTradeJournalEntry",
    "EXECUTION_ERROR", "EmergencyController", "EmergencyDecision", "EmergencySignals",
    "EmergencyTrigger", "ExecutionAttribution", "ExecutionComparator", "ExecutionLifecycle",
    "ExecutionMode", "ExecutionModeResolver", "ExecutionProposal", "ExecutionStateError",
    "ExitAction", "ExitReason", "ExitVerdict", "GATE_ORDER", "GateChainDecision", "GateOutcome",
    "IdempotencyRegistry", "IdempotencyVerdict", "MODEL_ERROR", "ManualApprovalQueue",
    "ModeDecision", "POSITIONS_UNTOUCHED", "PROPOSAL_BLOCKED", "PROPOSAL_EXPIRED",
    "PROPOSAL_NOT_FOUND", "PROPOSAL_NOT_PENDING", "PaperDemoComparison", "PositionMonitor",
    "PositionSize", "PositionSizer", "PositionSnapshot", "RISK_REJECTION",
    "SHUTDOWN_ACTION", "SIGNAL_QUALITY_ERROR", "SIMULATION_MODES", "SLIPPAGE_ERROR",
    "SPREAD_ERROR", "STRATEGY_ERROR", "StateTransition", "SymbolContract",
    "TERMINAL_STATES", "UnknownExecutionMode", "calculate_demo_performance",
    "execution_request_id", "parse_mode", "state_for_result",
]
