"""Exit decisions and exit reasons (sections 21 and 22).

Eight exit reasons, one of which is always recorded. A closed position with no
stated reason is a hole in the journal, so `decide()` never returns "exit"
without saying why.

Section 22 is the subtle part. An even-hour checkpoint is when the position is
*re-evaluated*, not when it is closed. The clock changing is not itself a reason
to be flat: at the checkpoint the configured exit policy is applied — higher and
lower timeframe trend, liquidity, structure, Ichimoku, RSI, ADX, the NN, the
strategy, risk, and time remaining — and a counter-trend position is held to a
stricter confidence bar than a with-trend one. Between checkpoints only the
conditions that do not wait for a clock apply: stop loss, take profit,
invalidation and a risk emergency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from observation.time_exit import ExitDecision as CheckpointDecision
from observation.time_exit import TimeExitAnalysis, TimeExitAnalyzer, TrendAlignment


class ExitReason(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TIME_EXIT = "TIME_EXIT"
    STRATEGY_EXIT = "STRATEGY_EXIT"
    STRUCTURE_INVALIDATION = "STRUCTURE_INVALIDATION"
    LIQUIDITY_INVALIDATION = "LIQUIDITY_INVALIDATION"
    RISK_EMERGENCY_EXIT = "RISK_EMERGENCY_EXIT"
    MANUAL_EXIT = "MANUAL_EXIT"


class ExitAction(StrEnum):
    HOLD = "HOLD"
    EXIT = "EXIT"
    WAIT = "WAIT"


# Conditions that do not wait for the even-hour clock, most decisive first.
IMMEDIATE_REASONS = (
    ExitReason.RISK_EMERGENCY_EXIT, ExitReason.STOP_LOSS, ExitReason.TAKE_PROFIT,
    ExitReason.STRUCTURE_INVALIDATION, ExitReason.LIQUIDITY_INVALIDATION,
)


@dataclass(frozen=True, slots=True)
class ExitVerdict:
    action: ExitAction
    reason: ExitReason | None
    reasons: tuple[str, ...] = ()
    at_checkpoint: bool = False
    alignment: str = str(TrendAlignment.NEUTRAL)
    required_confidence: float = 0.0
    confidence: float = 0.0
    next_checkpoint: datetime | None = None
    analysis: TimeExitAnalysis | None = None
    conditions: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def should_exit(self) -> bool:
        return self.action is ExitAction.EXIT

    def as_dict(self) -> dict[str, Any]:
        return {"action": str(self.action),
                "exit_reason": str(self.reason) if self.reason else None,
                "reasons": list(self.reasons), "at_checkpoint": self.at_checkpoint,
                "alignment": self.alignment,
                "required_confidence": self.required_confidence,
                "confidence": self.confidence, "next_checkpoint": self.next_checkpoint,
                "conditions": dict(self.conditions),
                "analysis": self.analysis.as_dict() if self.analysis else None,
                "timestamp": self.timestamp}


class DemoExitEngine:
    """Decides whether an open DEMO position should be closed, and states why."""

    def __init__(self, *, analyzer: TimeExitAnalyzer | None = None):
        self.analyzer = analyzer or TimeExitAnalyzer()

    @staticmethod
    def _stop_hit(*, direction: str, price: float, stop_loss: float | None) -> bool:
        if stop_loss is None or price <= 0:
            return False
        return price <= stop_loss if str(direction).upper() in {"BUY", "LONG"} else price >= stop_loss

    @staticmethod
    def _target_hit(*, direction: str, price: float, take_profit: float | None) -> bool:
        if take_profit is None or price <= 0:
            return False
        return price >= take_profit if str(direction).upper() in {"BUY", "LONG"} else price <= take_profit

    def decide(self, *, direction: str, entry_time: datetime, current_price: float,
               regime: Any, now: datetime | None = None, stop_loss: float | None = None,
               take_profit: float | None = None, strategy_confidence: float = 0.0,
               nn_confidence: float = 0.0, structure_valid: bool = True,
               liquidity_valid: bool = True, indicator_valid: bool = True,
               risk_allowed: bool = True, strategy_exit: bool = False,
               manual_exit: bool = False) -> ExitVerdict:
        moment = now or datetime.now(timezone.utc)
        analysis = self.analyzer.analyse(
            direction=direction, regime=regime, entry_time=entry_time, now=moment,
            strategy_confidence=strategy_confidence, nn_confidence=nn_confidence,
            structure_valid=structure_valid, liquidity_valid=liquidity_valid,
            indicator_valid=indicator_valid, risk_allowed=risk_allowed)
        conditions = {
            "structure_valid": structure_valid, "liquidity_valid": liquidity_valid,
            "indicator_valid": indicator_valid, "risk_allowed": risk_allowed,
            "regime": str(regime), "price": current_price,
            "stop_loss": stop_loss, "take_profit": take_profit,
            "holding_seconds": analysis.holding_seconds,
        }
        common = dict(at_checkpoint=analysis.at_checkpoint, alignment=str(analysis.alignment),
                      required_confidence=analysis.required_confidence,
                      confidence=min(float(strategy_confidence), float(nn_confidence)),
                      next_checkpoint=analysis.next_checkpoint, analysis=analysis,
                      conditions=conditions)

        # 1. Conditions that never wait for the clock.
        if manual_exit:
            return ExitVerdict(ExitAction.EXIT, ExitReason.MANUAL_EXIT,
                               ("OPERATOR_REQUESTED_EXIT",), **common)
        if not risk_allowed:
            return ExitVerdict(ExitAction.EXIT, ExitReason.RISK_EMERGENCY_EXIT,
                               ("RISK_BLOCKED",), **common)
        if self._stop_hit(direction=direction, price=current_price, stop_loss=stop_loss):
            return ExitVerdict(ExitAction.EXIT, ExitReason.STOP_LOSS,
                               ("STOP_LOSS_REACHED",), **common)
        if self._target_hit(direction=direction, price=current_price, take_profit=take_profit):
            return ExitVerdict(ExitAction.EXIT, ExitReason.TAKE_PROFIT,
                               ("TAKE_PROFIT_REACHED",), **common)
        if not structure_valid:
            return ExitVerdict(ExitAction.EXIT, ExitReason.STRUCTURE_INVALIDATION,
                               ("STRUCTURE_INVALIDATED",), **common)
        # Liquidity is deliberately NOT in this list: a single liquidity read is
        # noisier than a structural break, so it is weighed at the checkpoint below.
        if strategy_exit:
            return ExitVerdict(ExitAction.EXIT, ExitReason.STRATEGY_EXIT,
                               ("STRATEGY_REQUESTED_EXIT",), **common)

        # 2. Everything else is the configured even-hour policy.
        if analysis.decision is CheckpointDecision.WAIT:
            return ExitVerdict(ExitAction.WAIT, None, analysis.reasons, **common)
        if analysis.decision is CheckpointDecision.EXIT:
            reason = (ExitReason.LIQUIDITY_INVALIDATION
                      if "SUPPORTING_CONTEXT_WEAKENED" in analysis.reasons and not liquidity_valid
                      else ExitReason.TIME_EXIT)
            return ExitVerdict(ExitAction.EXIT, reason, analysis.reasons, **common)
        return ExitVerdict(ExitAction.HOLD, None, analysis.reasons, **common)
