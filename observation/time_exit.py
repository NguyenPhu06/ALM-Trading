"""Even-hour checkpoint exit analysis. Nothing is closed in this phase.

The concept: a position is re-evaluated at configured even-hour checkpoints
rather than continuously. If its direction opposes the higher-timeframe regime it
is marked COUNTER_TREND and held to a stricter confidence bar.

`decide()` returns HOLD, EXIT or WAIT. It never closes anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from config.settings import load_yaml
from observation.regime import MarketRegime


class ExitDecision(StrEnum):
    HOLD = "HOLD"
    EXIT = "EXIT"
    WAIT = "WAIT"


class TrendAlignment(StrEnum):
    WITH_TREND = "WITH_TREND"
    COUNTER_TREND = "COUNTER_TREND"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class TimeExitAnalysis:
    decision: ExitDecision
    alignment: TrendAlignment
    next_checkpoint: datetime
    seconds_to_checkpoint: float
    at_checkpoint: bool
    holding_seconds: float
    required_confidence: float
    strategy_confidence: float
    nn_confidence: float
    reasons: tuple[str, ...] = ()
    conditions: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def executed(self) -> bool:
        """Always False. Phase 12 analyses; it does not close positions."""
        return False

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": str(self.decision), "alignment": str(self.alignment),
            "next_checkpoint": self.next_checkpoint,
            "seconds_to_checkpoint": round(self.seconds_to_checkpoint, 1),
            "at_checkpoint": self.at_checkpoint,
            "holding_seconds": round(self.holding_seconds, 1),
            "required_confidence": self.required_confidence,
            "strategy_confidence": self.strategy_confidence,
            "nn_confidence": self.nn_confidence,
            "reasons": list(self.reasons), "conditions": dict(self.conditions),
            "executed": False, "timestamp": self.timestamp,
        }


class TimeExitAnalyzer:
    def __init__(self, *, checkpoint_hours: int | None = None,
                 max_holding_hours: float | None = None,
                 counter_trend_min_confidence: float | None = None,
                 base_min_confidence: float = 0.45):
        config = load_yaml().get("phase_12", {}).get("time_exit", {})
        self.checkpoint_hours = int(
            checkpoint_hours if checkpoint_hours is not None else config.get("checkpoint_hours", 2))
        self.max_holding = timedelta(hours=float(
            max_holding_hours if max_holding_hours is not None
            else config.get("max_holding_hours", 8)))
        self.counter_trend_min_confidence = float(
            counter_trend_min_confidence if counter_trend_min_confidence is not None
            else config.get("counter_trend_min_confidence", 0.75))
        self.base_min_confidence = float(base_min_confidence)

    def next_checkpoint(self, moment: datetime) -> datetime:
        """The next wall-clock hour divisible by `checkpoint_hours`."""
        step = max(1, self.checkpoint_hours)
        anchor = moment.replace(minute=0, second=0, microsecond=0)
        if anchor <= moment:
            anchor += timedelta(hours=1)
        while anchor.hour % step != 0:
            anchor += timedelta(hours=1)
        return anchor

    @staticmethod
    def alignment_for(direction: str, regime: MarketRegime | str) -> TrendAlignment:
        side = str(direction).strip().upper()
        state = str(regime)
        if state in {str(MarketRegime.RANGE), str(MarketRegime.UNKNOWN)}:
            return TrendAlignment.NEUTRAL
        bullish_regime = state in {str(MarketRegime.BULL), str(MarketRegime.STRONG_BULL)}
        long_side = side in {"BUY", "LONG"}
        return TrendAlignment.WITH_TREND if bullish_regime == long_side else TrendAlignment.COUNTER_TREND

    def analyse(self, *, direction: str, regime: MarketRegime | str, entry_time: datetime,
                now: datetime | None = None, strategy_confidence: float = 0.0,
                nn_confidence: float = 0.0, structure_valid: bool = True,
                liquidity_valid: bool = True, indicator_valid: bool = True,
                risk_allowed: bool = True) -> TimeExitAnalysis:
        moment = now or datetime.now(timezone.utc)
        checkpoint = self.next_checkpoint(moment)
        seconds = (checkpoint - moment).total_seconds()
        holding = (moment - entry_time).total_seconds()
        # A checkpoint hour with the minute at zero counts as being on it.
        at_checkpoint = moment.hour % max(1, self.checkpoint_hours) == 0 and moment.minute == 0

        alignment = self.alignment_for(direction, regime)
        required = (self.counter_trend_min_confidence
                    if alignment is TrendAlignment.COUNTER_TREND else self.base_min_confidence)
        conditions = {
            "structure_valid": structure_valid, "liquidity_valid": liquidity_valid,
            "indicator_valid": indicator_valid, "risk_allowed": risk_allowed,
            "regime": str(regime),
        }
        reasons: list[str] = [f"ALIGNMENT_{alignment}"]

        # Conditions that call for an exit regardless of the checkpoint clock.
        if not risk_allowed:
            reasons.append("RISK_BLOCKED")
            return TimeExitAnalysis(ExitDecision.EXIT, alignment, checkpoint, seconds,
                                    at_checkpoint, holding, required, strategy_confidence,
                                    nn_confidence, tuple(reasons), conditions)
        if not structure_valid:
            reasons.append("STRUCTURE_INVALIDATED")
            return TimeExitAnalysis(ExitDecision.EXIT, alignment, checkpoint, seconds,
                                    at_checkpoint, holding, required, strategy_confidence,
                                    nn_confidence, tuple(reasons), conditions)
        if holding >= self.max_holding.total_seconds():
            reasons.append("MAX_HOLDING_REACHED")
            return TimeExitAnalysis(ExitDecision.EXIT, alignment, checkpoint, seconds,
                                    at_checkpoint, holding, required, strategy_confidence,
                                    nn_confidence, tuple(reasons), conditions)

        # Otherwise the decision is only taken at a checkpoint.
        if not at_checkpoint:
            reasons.append("AWAITING_NEXT_CHECKPOINT")
            return TimeExitAnalysis(ExitDecision.WAIT, alignment, checkpoint, seconds,
                                    at_checkpoint, holding, required, strategy_confidence,
                                    nn_confidence, tuple(reasons), conditions)

        confidence = min(float(strategy_confidence), float(nn_confidence))
        if confidence < required:
            reasons.append("CONFIDENCE_BELOW_REQUIREMENT")
            if alignment is TrendAlignment.COUNTER_TREND:
                reasons.append("COUNTER_TREND_STRICTER_BAR")
            return TimeExitAnalysis(ExitDecision.EXIT, alignment, checkpoint, seconds,
                                    at_checkpoint, holding, required, strategy_confidence,
                                    nn_confidence, tuple(reasons), conditions)
        if not (liquidity_valid and indicator_valid):
            reasons.append("SUPPORTING_CONTEXT_WEAKENED")
            return TimeExitAnalysis(ExitDecision.EXIT, alignment, checkpoint, seconds,
                                    at_checkpoint, holding, required, strategy_confidence,
                                    nn_confidence, tuple(reasons), conditions)

        reasons.append("CONDITIONS_STILL_VALID")
        return TimeExitAnalysis(ExitDecision.HOLD, alignment, checkpoint, seconds,
                                at_checkpoint, holding, required, strategy_confidence,
                                nn_confidence, tuple(reasons), conditions)
