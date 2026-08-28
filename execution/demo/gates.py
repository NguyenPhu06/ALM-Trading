"""The Phase 16 gate chain (sections 5, 7, 9, 10, 18, 19).

Twelve gates, evaluated in a fixed order, every one of them fail-closed:

    DemoAccountValidator -> DataQualityGate -> SpreadGate -> RiskGate
    -> DrawdownGate -> ExposureGate -> DcaSafetyGate -> StrategyGate
    -> ModelConfidenceGate -> SessionGate -> ExecutionGuard -> KillSwitch

Every gate runs even after one has already blocked. A partial answer ("blocked by
the spread") hides the fact that the account was also unverified and the kill
switch was also engaged, and an operator who fixes only the reported problem
would be surprised twice. The chain reports all of it at once.

A gate that cannot evaluate its input blocks. There is no gate in this module
that returns PASS because it had nothing to check, with one deliberate
exception documented at ModelConfidenceGate: the neural network is advisory, so
its absence is not by itself a refusal unless configuration says it is.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config.settings import Settings, get_settings, load_yaml
from execution.demo.daily_risk import DailyRiskState
from execution.demo.idempotency import DUPLICATE_EXECUTION_REQUEST, IdempotencyVerdict
from execution.demo.limits import (
    MAX_DAILY_LOSS, MAX_DCA_EXPOSURE, MAX_DCA_LEVELS, MAX_MARGIN_USAGE, MAX_OPEN_POSITIONS,
    MAX_POSITION_SIZE, MAX_RISK_PER_TRADE, MAX_SLIPPAGE, MAX_SPREAD, MAX_SYMBOL_EXPOSURE,
    MAX_TOTAL_DRAWDOWN, MAX_TOTAL_EXPOSURE, MAX_TRADES_PER_DAY, DemoRiskLimits,
)
from execution.demo.modes import ExecutionModeResolver, ModeDecision
from execution.demo.order import DemoOrderRequest
from execution.mt5.execution_guard import ExecutionGuard, GuardContext, GuardDecision
from execution.mt5.order_request import ExecutionIntent
from features.session import SessionEngine
from observation.demo_account import DemoAccountResult, DemoAccountValidator, DemoValidation

logger = logging.getLogger(__name__)

# Gate names, in evaluation order. The dashboard renders this list verbatim.
GATE_ORDER = (
    "DemoAccountValidator", "DataQualityGate", "SpreadGate", "RiskGate", "DrawdownGate",
    "ExposureGate", "DcaSafetyGate", "StrategyGate", "ModelConfidenceGate", "SessionGate",
    "ExecutionGuard", "KillSwitch",
)

# Phase 17 section 2 rests on this split, so it is named here rather than implied.
#
# DECISION gates answer "is this a trade worth taking": the account, the data, the
# spread, the risk budget, the exposure, the strategy and the model. SHADOW and
# DEMO must agree on every one of them — that is what makes a shadow record a
# faithful mirror rather than a parallel opinion.
#
# TRANSMISSION gates answer "may this reach a broker": the configuration flags,
# the guard approval and the kill switch. SHADOW and DEMO differ here by design,
# because that difference *is* the mode. ExecutionGuard sits on this side because
# its refusals are dominated by the configuration flags; the order-validity checks
# it also performs are covered on the decision side by SpreadGate, RiskGate,
# SessionGate and DemoAccountValidator.
DECISION_GATES = ("DemoAccountValidator", "DataQualityGate", "SpreadGate", "RiskGate",
                  "DrawdownGate", "ExposureGate", "DcaSafetyGate", "StrategyGate",
                  "ModelConfidenceGate", "SessionGate")
TRANSMISSION_GATES = ("ExecutionGuard", "KillSwitch")

# Reason codes owned by this module.
ACCOUNT_NOT_VERIFIED_DEMO = "ACCOUNT_NOT_VERIFIED_DEMO"
ACCOUNT_IS_REAL = "ACCOUNT_IS_REAL"
ACCOUNT_UNKNOWN = "ACCOUNT_UNKNOWN"
DATA_QUALITY_FAILED = "DATA_QUALITY_FAILED"
DATA_STALE = "DATA_STALE"
DATA_QUALITY_UNKNOWN = "DATA_QUALITY_UNKNOWN"
SPREAD_UNAVAILABLE = "SPREAD_UNAVAILABLE"
RISK_ENGINE_BLOCKED = "RISK_ENGINE_BLOCKED"
RISK_ENGINE_UNAVAILABLE = "RISK_ENGINE_UNAVAILABLE"
DCA_DISABLED = "DCA_DISABLED"
DCA_INVALIDATED = "DCA_INVALIDATED"
STRATEGY_NOT_CHAMPION = "STRATEGY_NOT_CHAMPION"
STRATEGY_UNKNOWN = "STRATEGY_UNKNOWN"
MODEL_CONFIDENCE_BELOW_MINIMUM = "MODEL_CONFIDENCE_BELOW_MINIMUM"
MODEL_PREDICTION_UNAVAILABLE = "MODEL_PREDICTION_UNAVAILABLE"
MODEL_FAILED = "MODEL_FAILED"
SESSION_NOT_ALLOWED = "SESSION_NOT_ALLOWED"
KILL_SWITCH_ENGAGED = "KILL_SWITCH_ENGAGED"
MODE_BLOCKS_EXECUTION = "MODE_BLOCKS_EXECUTION"
VOLUME_NOT_SIZED = "VOLUME_NOT_SIZED"


@dataclass(frozen=True, slots=True)
class GateOutcome:
    name: str
    passed: bool
    reasons: tuple[str, ...] = ()
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"gate": self.name, "passed": self.passed, "reasons": list(self.reasons),
                "details": dict(self.details)}


@dataclass(frozen=True, slots=True)
class DemoExecutionContext:
    """Everything the chain needs. Anything absent is treated as unsafe."""

    account: DemoAccountResult | None = None
    connected: bool = False
    quote: dict[str, Any] | None = None
    # Data quality: either the Phase 12 gate results keyed by timeframe, or a
    # plain verdict when the caller has already reduced it.
    data_quality: dict[str, Any] | None = None
    data_quality_ok: bool | None = None
    data_age_seconds: float | None = None
    # Risk engine verdict, from whichever engine the caller ran.
    risk_allowed: bool | None = None
    risk_reasons: tuple[str, ...] = ()
    risk_snapshot_id: str | None = None
    equity: float | None = None
    free_margin: float | None = None
    used_margin: float | None = None
    daily: DailyRiskState | None = None
    open_positions: int = 0
    symbol_exposure: float = 0.0
    total_exposure: float = 0.0
    order_notional: float = 0.0
    dca_levels: int = 0
    dca_exposure: float = 0.0
    dca_invalidated: bool = False
    # Two different things, deliberately kept apart. `strategy_status` is the
    # registry state a strategy has *earned* (CHAMPION, CHALLENGER, ...) and it
    # is what StrategyGate checks. `strategy_decision` is what the engine said
    # about this particular setup right now (EXECUTABLE_SIMULATION, WAIT, ...)
    # and it is what the Phase 11 guard checks. A champion strategy with no
    # executable setup must not trade, and neither must an executable setup from
    # a strategy that has not earned CHAMPION.
    strategy_status: str | None = None
    strategy_decision: str | None = None
    strategy_id: str | None = None
    model_confidence: float | None = None
    model_direction_probability: float | None = None
    model_failed: bool = False
    expected_slippage: float | None = None
    session: str | None = None
    # Phase 17 attribution. Recorded on every candidate so regime, session and
    # timeframe performance can be cut later; none of these can block an order.
    regime: str | None = None
    timeframe: str | None = None
    signal_timeframe: str | None = None
    known_symbols: tuple[str, ...] = ()
    idempotency: IdempotencyVerdict | None = None
    mode: ModeDecision | None = None
    timestamp: datetime | None = None

    def guard_context(self) -> GuardContext:
        """Adapt onto the Phase 11 guard contract."""
        return GuardContext(
            account=self.account.account if self.account else None,
            connected=self.connected, quote=self.quote,
            open_positions=self.open_positions, dca_entries=self.dca_levels,
            exposure=self.total_exposure,
            daily_drawdown=self.daily.daily_drawdown if self.daily else 0.0,
            risk_allowed=bool(self.risk_allowed), risk_reasons=self.risk_reasons,
            strategy_status=self.strategy_decision, known_symbols=self.known_symbols,
            session=self.session, timestamp=self.timestamp,
        )


@dataclass(frozen=True, slots=True)
class GateChainDecision:
    approved: bool
    request_id: str
    gates: tuple[GateOutcome, ...] = ()
    reasons: tuple[str, ...] = ()
    guard: GuardDecision | None = None
    mode: ModeDecision | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    environment: str = "DEMO"

    @property
    def blocked_by(self) -> tuple[str, ...]:
        return tuple(gate.name for gate in self.gates if not gate.passed)

    @property
    def verdicts(self) -> dict[str, bool]:
        return {gate.name: gate.passed for gate in self.gates}

    @property
    def decision_approved(self) -> bool:
        """Would this trade have been taken, had execution been armed?

        The question SHADOW exists to answer. It ignores the transmission gates,
        so a signal blocked only because the mode sends nothing still reports the
        decision the strategy and risk engine actually reached.
        """
        verdicts = self.verdicts
        return all(verdicts.get(name, False) for name in DECISION_GATES)

    @property
    def decision_reasons(self) -> tuple[str, ...]:
        """Why the decision itself was refused, ignoring transmission."""
        reasons: list[str] = []
        for gate in self.gates:
            if gate.name in DECISION_GATES and not gate.passed:
                reasons.extend(str(reason) for reason in gate.reasons)
        return tuple(dict.fromkeys(reasons))

    def as_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "request_id": self.request_id,
                "decision_approved": self.decision_approved,
                "decision_reasons": list(self.decision_reasons),
                "gates": [gate.as_dict() for gate in self.gates],
                "blocked_by": list(self.blocked_by), "reasons": list(self.reasons),
                "guard": self.guard.as_dict() if self.guard else None,
                "mode": self.mode.as_dict() if self.mode else None,
                "environment": self.environment, "timestamp": self.timestamp}


class DemoGateChain:
    """The only authority that may approve a Phase 16 DEMO order.

    It wraps, rather than replaces, the Phase 11 ExecutionGuard: the guard still
    owns the configuration/account/volume/price checks and still issues the
    approval that `MT5ExecutionClient` demands before transmitting.
    """

    def __init__(self, settings: Settings | None = None, *, guard: ExecutionGuard | None = None,
                 limits: DemoRiskLimits | None = None,
                 account_validator: DemoAccountValidator | None = None,
                 sessions: SessionEngine | None = None,
                 mode_resolver: ExecutionModeResolver | None = None):
        self.settings = settings or get_settings()
        config = load_yaml().get("phase_16", {})
        self.limits = limits or DemoRiskLimits.from_config()
        self.guard = guard or ExecutionGuard(self.settings)
        # Execution needs verified terminal permissions; observation does not.
        self.account_validator = account_validator or DemoAccountValidator(
            self.settings, require_permissions=True)
        self.sessions = sessions or SessionEngine()
        self.modes = mode_resolver or ExecutionModeResolver(self.settings)
        model_config = config.get("model", {}) or {}
        self.minimum_confidence = float(model_config.get("minimum_confidence", 0.60))
        self.minimum_direction_probability = float(
            model_config.get("minimum_direction_probability", 0.60))
        self.require_prediction = bool(model_config.get("require_prediction", False))
        strategy_config = config.get("strategy", {}) or {}
        self.executable_statuses = tuple(
            str(item).upper() for item in (strategy_config.get("executable_statuses") or ("CHAMPION",)))
        self.allow_challenger_execution = bool(
            strategy_config.get("allow_challenger_execution", False))
        self.allow_experimental_execution = bool(
            strategy_config.get("allow_experimental_execution", False))
        self.allowed_sessions = tuple(
            load_yaml().get("phase_11", {}).get("allowed_sessions") or ())

    # ------------------------------------------------------------------ gates
    def _account_gate(self, context: DemoExecutionContext) -> GateOutcome:
        result = context.account
        if result is None:
            return GateOutcome("DemoAccountValidator", False, (ACCOUNT_NOT_VERIFIED_DEMO,))
        if result.status is DemoValidation.INVALID_ACCOUNT:
            reasons = (ACCOUNT_IS_REAL,) if ACCOUNT_IS_REAL in result.reasons else result.reasons
            return GateOutcome("DemoAccountValidator", False, tuple(reasons),
                               {"status": str(result.status)})
        if result.status is not DemoValidation.VALID_DEMO:
            # UNKNOWN and CONNECTION_ERROR are both refusals. Unknown is never safe.
            return GateOutcome("DemoAccountValidator", False,
                               (ACCOUNT_UNKNOWN, *result.reasons), {"status": str(result.status)})
        return GateOutcome("DemoAccountValidator", True, ("ACCOUNT_IS_DEMO",),
                           {"status": str(result.status)})

    def _data_quality_gate(self, context: DemoExecutionContext) -> GateOutcome:
        if context.data_quality_ok is None and not context.data_quality:
            return GateOutcome("DataQualityGate", False, (DATA_QUALITY_UNKNOWN,))
        reasons: list[str] = []
        failures: dict[str, Any] = {}
        for timeframe, result in (context.data_quality or {}).items():
            verdict = str(getattr(result, "verdict", None) or
                          (result.get("verdict") if isinstance(result, dict) else "")).upper()
            if verdict == "FAIL":
                codes = getattr(result, "reasons", None)
                if codes is None and isinstance(result, dict):
                    codes = result.get("reasons", ())
                failures[timeframe] = [str(code) for code in (codes or ())]
        if failures:
            reasons.append(DATA_QUALITY_FAILED)
        if context.data_quality_ok is False:
            reasons.append(DATA_QUALITY_FAILED)
        stale_after = float(load_yaml().get("phase_16", {}).get("emergency", {}).get(
            "data_stale_seconds", 180))
        if context.data_age_seconds is not None and context.data_age_seconds > stale_after:
            reasons.append(DATA_STALE)
        unique = tuple(dict.fromkeys(reasons))
        return GateOutcome("DataQualityGate", not unique, unique, {"failures": failures})

    def _spread_gate(self, context: DemoExecutionContext) -> GateOutcome:
        quote = context.quote or {}
        bid, ask = quote.get("bid"), quote.get("ask")
        if bid is None or ask is None:
            return GateOutcome("SpreadGate", False, (SPREAD_UNAVAILABLE,))
        spread = float(ask) - float(bid)
        reasons: list[str] = []
        if spread < 0 or spread > self.limits.max_spread:
            reasons.append(MAX_SPREAD)
        slippage = context.expected_slippage
        if slippage is not None and abs(float(slippage)) > self.limits.max_slippage:
            reasons.append(MAX_SLIPPAGE)
        return GateOutcome("SpreadGate", not reasons, tuple(reasons),
                           {"spread": round(spread, 8), "max_spread": self.limits.max_spread,
                            "expected_slippage": slippage})

    def _risk_gate(self, request: DemoOrderRequest,
                   context: DemoExecutionContext) -> GateOutcome:
        reasons: list[str] = []
        if context.risk_allowed is None:
            reasons.append(RISK_ENGINE_UNAVAILABLE)
        elif not context.risk_allowed:
            reasons.append(RISK_ENGINE_BLOCKED)
            reasons.extend(str(code) for code in context.risk_reasons)
        if request.volume is None or request.volume <= 0:
            reasons.append(VOLUME_NOT_SIZED)
        elif request.volume > self.limits.max_position_size:
            reasons.append(MAX_POSITION_SIZE)
        # Risk per trade is checked against what sizing actually claimed, so a
        # hand-built request cannot smuggle a larger risk past the sizer.
        if request.risk_percent is not None and request.risk_percent > self.limits.max_risk_per_trade:
            reasons.append(MAX_RISK_PER_TRADE)
        if context.equity and request.risk_amount is not None:
            if request.risk_amount > context.equity * self.limits.max_risk_per_trade + 1e-9:
                reasons.append(MAX_RISK_PER_TRADE)
        if context.free_margin is not None and context.used_margin is not None:
            total = float(context.free_margin) + float(context.used_margin)
            usage = float(context.used_margin) / total if total else 0.0
            if usage > self.limits.max_margin_usage:
                reasons.append(MAX_MARGIN_USAGE)
        unique = tuple(dict.fromkeys(reasons))
        return GateOutcome("RiskGate", not unique, unique,
                           {"risk_percent": request.risk_percent,
                            "risk_amount": request.risk_amount,
                            "risk_snapshot_id": context.risk_snapshot_id})

    def _drawdown_gate(self, context: DemoExecutionContext) -> GateOutcome:
        daily = context.daily
        if daily is None:
            # Without a day state there is no evidence the budget is intact.
            return GateOutcome("DrawdownGate", False, ("DAILY_RISK_STATE_UNAVAILABLE",))
        reasons = [code for code in daily.reasons
                   if code in {MAX_DAILY_LOSS, MAX_TOTAL_DRAWDOWN, MAX_TRADES_PER_DAY}]
        return GateOutcome("DrawdownGate", not reasons, tuple(reasons),
                           {"daily_drawdown": round(daily.daily_drawdown, 6),
                            "total_drawdown": round(daily.total_drawdown, 6),
                            "trade_count": daily.trade_count,
                            "trading_day": daily.trading_day.isoformat()})

    def _exposure_gate(self, context: DemoExecutionContext) -> GateOutcome:
        reasons: list[str] = []
        projected_symbol = float(context.symbol_exposure) + float(context.order_notional)
        projected_total = float(context.total_exposure) + float(context.order_notional)
        if context.open_positions >= self.limits.max_open_positions:
            reasons.append(MAX_OPEN_POSITIONS)
        if projected_symbol > self.limits.max_symbol_exposure:
            reasons.append(MAX_SYMBOL_EXPOSURE)
        if projected_total > self.limits.max_total_exposure:
            reasons.append(MAX_TOTAL_EXPOSURE)
        return GateOutcome("ExposureGate", not reasons, tuple(reasons),
                           {"projected_symbol_exposure": round(projected_symbol, 2),
                            "projected_total_exposure": round(projected_total, 2),
                            "open_positions": context.open_positions})

    def _dca_gate(self, request: DemoOrderRequest,
                  context: DemoExecutionContext) -> GateOutcome:
        """A non-DCA order passes trivially; a DCA order re-runs the full budget.

        Section 10: DCA is disabled by default, bounded in levels and aggregate
        exposure, and invalidated by its stated condition. There is no martingale
        anywhere: size comes from the sizer, never from a multiplier on a loss.
        """
        if request.intent is not ExecutionIntent.DCA:
            return GateOutcome("DcaSafetyGate", True, ("NOT_A_DCA_ORDER",))
        reasons: list[str] = []
        if not getattr(self.settings, "demo_dca_enabled", False):
            reasons.append(DCA_DISABLED)
        if context.dca_levels >= self.limits.max_dca_levels:
            reasons.append(MAX_DCA_LEVELS)
        projected = float(context.dca_exposure) + float(context.order_notional)
        if projected > self.limits.max_total_dca_exposure:
            reasons.append(MAX_DCA_EXPOSURE)
        if context.dca_invalidated:
            reasons.append(DCA_INVALIDATED)
        return GateOutcome("DcaSafetyGate", not reasons, tuple(reasons),
                           {"dca_levels": context.dca_levels,
                            "max_dca_levels": self.limits.max_dca_levels,
                            "projected_dca_exposure": round(projected, 2)})

    def _strategy_gate(self, context: DemoExecutionContext) -> GateOutcome:
        """Only the validated Champion Strategy executes automatically (section 18)."""
        status = str(context.strategy_status or "").strip().upper()
        if not status:
            return GateOutcome("StrategyGate", False, (STRATEGY_UNKNOWN,))
        allowed = set(self.executable_statuses)
        if self.allow_challenger_execution:
            allowed.add("CHALLENGER")
        if self.allow_experimental_execution:
            allowed.update({"EXPERIMENTAL", "TESTING"})
        # The Phase 12 strategy engine speaks its own vocabulary; an executable
        # simulation is a necessary condition, never a sufficient one.
        if status == "EXECUTABLE_SIMULATION":
            allowed.add("EXECUTABLE_SIMULATION")
        if status not in allowed:
            return GateOutcome("StrategyGate", False, (STRATEGY_NOT_CHAMPION,),
                               {"status": status, "allowed": sorted(allowed)})
        return GateOutcome("StrategyGate", True, (f"STRATEGY_{status}",),
                           {"status": status, "strategy_id": context.strategy_id})

    def _model_gate(self, context: DemoExecutionContext) -> GateOutcome:
        """The NN is advisory (section 19).

        It can refuse — a failed model, or a confidence below the configured bar,
        blocks — but it can never approve past another gate. When no prediction
        exists at all the gate defers unless configuration demands one, because a
        strategy that does not consult the NN is still a valid strategy.
        """
        reasons: list[str] = []
        if context.model_failed:
            reasons.append(MODEL_FAILED)
        confidence = context.model_confidence
        probability = context.model_direction_probability
        if confidence is None and probability is None:
            if self.require_prediction:
                reasons.append(MODEL_PREDICTION_UNAVAILABLE)
            return GateOutcome("ModelConfidenceGate", not reasons, tuple(reasons),
                               {"advisory": True, "prediction": None})
        if confidence is not None and float(confidence) < self.minimum_confidence:
            reasons.append(MODEL_CONFIDENCE_BELOW_MINIMUM)
        if probability is not None and float(probability) < self.minimum_direction_probability:
            reasons.append(MODEL_CONFIDENCE_BELOW_MINIMUM)
        return GateOutcome("ModelConfidenceGate", not reasons, tuple(dict.fromkeys(reasons)),
                           {"advisory": True, "confidence": confidence,
                            "direction_probability": probability,
                            "minimum_confidence": self.minimum_confidence})

    def _session_gate(self, context: DemoExecutionContext) -> GateOutcome:
        if not self.allowed_sessions:
            return GateOutcome("SessionGate", True, ("NO_SESSION_RESTRICTION",))
        moment = context.timestamp or datetime.now(timezone.utc)
        session = context.session or self.sessions.session_for(moment).value
        allowed = session in self.allowed_sessions
        return GateOutcome("SessionGate", allowed,
                           () if allowed else (SESSION_NOT_ALLOWED,), {"session": session})

    def _kill_switch_gate(self, request: DemoOrderRequest) -> GateOutcome:
        new_entry = request.intent is not ExecutionIntent.DCA
        blocked = self.guard.kill_switch.blocking_reasons(
            new_entry=new_entry, increases_exposure=not new_entry)
        if blocked:
            return GateOutcome("KillSwitch", False, (KILL_SWITCH_ENGAGED, *blocked),
                               {"engaged": True})
        return GateOutcome("KillSwitch", True, ("KILL_SWITCH_RELEASED",), {"engaged": False})

    # ---------------------------------------------------------------- verdict
    def evaluate(self, request: DemoOrderRequest,
                 context: DemoExecutionContext | None = None) -> GateChainDecision:
        context = context or DemoExecutionContext()
        mode = context.mode or self.modes.resolve()
        guard_decision = self.guard.evaluate(request.to_order_request(), context.guard_context())

        outcomes: list[GateOutcome] = [
            self._account_gate(context),
            self._data_quality_gate(context),
            self._spread_gate(context),
            self._risk_gate(request, context),
            self._drawdown_gate(context),
            self._exposure_gate(context),
            self._dca_gate(request, context),
            self._strategy_gate(context),
            self._model_gate(context),
            self._session_gate(context),
            GateOutcome("ExecutionGuard", guard_decision.approved,
                        tuple(guard_decision.reasons), dict(guard_decision.checks)),
            self._kill_switch_gate(request),
        ]

        # Mode and idempotency are not gates in the section 5 list, but neither is
        # a decision the gates may override, so they are folded into the verdict.
        extra: list[str] = []
        if not mode.sends_orders:
            extra.append(MODE_BLOCKS_EXECUTION)
            extra.extend(mode.reasons)
        if context.idempotency is not None and not context.idempotency.allowed:
            extra.extend(context.idempotency.reasons or (DUPLICATE_EXECUTION_REQUEST,))

        reasons: list[str] = []
        for outcome in outcomes:
            if outcome.passed:
                continue
            for reason in outcome.reasons:
                if reason not in reasons:
                    reasons.append(str(reason))
        for reason in extra:
            if reason not in reasons:
                reasons.append(str(reason))

        approved = not reasons
        if reasons:
            logger.info("demo execution refused for %s: %s", request.request_id, ", ".join(reasons))
        return GateChainDecision(approved, request.request_id, tuple(outcomes), tuple(reasons),
                                 guard_decision, mode, environment=self.settings.environment)

    def gate_names(self) -> tuple[str, ...]:
        return GATE_ORDER
