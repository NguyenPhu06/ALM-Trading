from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum


class ExitAction(StrEnum):
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    INVALIDATE = "INVALIDATE"
    REASSESS = "REASSESS"


@dataclass(frozen=True, slots=True)
class ExitDecision:
    timestamp: datetime
    action: ExitAction
    reason_codes: tuple[str, ...]


class TimeExitEngine:
    def __init__(self, *, timezone_engine, max_holding_time: timedelta = timedelta(hours=8)):
        self.sessions = timezone_engine
        self.max_holding_time = max_holding_time

    def evaluate(self, *, entry_time: datetime, timestamp: datetime, structure_valid: bool,
                 regime_valid: bool, risk_allowed: bool, confidence: float,
                 drawdown: float, next_even_hour_only: bool = True) -> ExitDecision:
        if not structure_valid: return ExitDecision(timestamp, ExitAction.INVALIDATE, ("EXIT_STRUCTURE_INVALIDATED",))
        if not regime_valid: return ExitDecision(timestamp, ExitAction.EXIT, ("EXIT_REGIME_CHANGED",))
        if not risk_allowed: return ExitDecision(timestamp, ExitAction.EXIT, ("EXIT_RISK_LIMIT",))
        if timestamp - entry_time >= self.max_holding_time: return ExitDecision(timestamp, ExitAction.EXIT, ("EXIT_TIME_LIMIT",))
        if next_even_hour_only and not self.sessions.time_features(timestamp).is_even_hour:
            return ExitDecision(timestamp, ExitAction.HOLD, ("HOLD_UNTIL_NEXT_CHECKPOINT",))
        if drawdown > .01 or confidence < .45: return ExitDecision(timestamp, ExitAction.REDUCE, ("REDUCE_WEAKENING_CONTEXT",))
        return ExitDecision(timestamp, ExitAction.HOLD, ("HOLD_TREND_REMAINS_VALID", "HOLD_HIGH_CONFIDENCE"))

