"""Execution simulation — the terminal stage of every observation cycle.

For each strategy decision the cycle records what WOULD have happened:

    SIGNAL = BUY
    RISK = APPROVED
    EXECUTION = BLOCKED
    REASON = MT5_EXECUTION_DISABLED

This lets the entire pipeline be exercised against the live market with zero
orders sent. `orders_sent` is a constant 0 and there is no transport here at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from config.settings import Settings, get_settings


class SignalAction(StrEnum):
    """The vocabulary a strategy may emit. None of these submits anything."""

    WAIT = "WAIT"
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    EXIT = "EXIT"
    DCA = "DCA"


class RiskVerdict(StrEnum):
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"
    NOT_REQUIRED = "NOT_REQUIRED"


class ExecutionVerdict(StrEnum):
    BLOCKED = "BLOCKED"
    SIMULATED = "SIMULATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# Why execution was blocked, most decisive first.
OBSERVATION_MODE_ACTIVE = "OBSERVATION_MODE_ACTIVE"
MT5_EXECUTION_DISABLED = "MT5_EXECUTION_DISABLED"
DEMO_TRADING_DISABLED = "DEMO_TRADING_DISABLED"
KILL_SWITCH_ACTIVE = "KILL_SWITCH_ACTIVE"
LIVE_TRADING_DISABLED = "LIVE_TRADING_DISABLED"
RISK_BLOCKED = "RISK_BLOCKED"
DATA_QUALITY_FAILED = "DATA_QUALITY_FAILED"
ACCOUNT_NOT_DEMO = "ACCOUNT_NOT_DEMO"
NO_ACTIONABLE_SIGNAL = "NO_ACTIONABLE_SIGNAL"

ACTIONABLE = frozenset({SignalAction.BUY, SignalAction.SELL, SignalAction.DCA, SignalAction.EXIT})


@dataclass(frozen=True, slots=True)
class ExecutionSimulation:
    simulation_id: str
    symbol: str
    signal: SignalAction
    risk: RiskVerdict
    execution: ExecutionVerdict
    reasons: tuple[str, ...]
    confidence: float = 0.0
    hypothetical_entry: float | None = None
    hypothetical_volume: float | None = None
    hypothetical_sl: float | None = None
    hypothetical_tp: float | None = None
    environment: str = "DEMO"
    observation_mode: bool = True
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = field(default_factory=dict)

    # There is no code path in this module that transmits anything.
    orders_sent: int = 0

    @property
    def blocked(self) -> bool:
        return self.execution is not ExecutionVerdict.SIMULATED

    @property
    def primary_reason(self) -> str | None:
        return self.reasons[0] if self.reasons else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "simulation_id": self.simulation_id, "symbol": self.symbol,
            "signal": str(self.signal), "risk": str(self.risk),
            "execution": str(self.execution), "reason": self.primary_reason,
            "reasons": list(self.reasons), "confidence": self.confidence,
            "hypothetical_entry": self.hypothetical_entry,
            "hypothetical_volume": self.hypothetical_volume,
            "hypothetical_sl": self.hypothetical_sl, "hypothetical_tp": self.hypothetical_tp,
            "environment": self.environment, "observation_mode": self.observation_mode,
            "orders_sent": 0, "timestamp": self.timestamp, "context": dict(self.context),
        }

    def summary(self) -> str:
        return (f"SIGNAL = {self.signal}\nRISK = {self.risk}\n"
                f"EXECUTION = {self.execution}\nREASON = {self.primary_reason}")


class ExecutionSimulator:
    """Decides why an order would not have been sent, without ever sending one."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def blocking_reasons(self, *, risk_approved: bool = True, data_quality_ok: bool = True,
                         demo_account_valid: bool = True,
                         kill_switch_engaged: bool | None = None) -> list[str]:
        settings = self.settings
        reasons: list[str] = []
        if getattr(settings, "observation_mode", True):
            reasons.append(OBSERVATION_MODE_ACTIVE)
        if not getattr(settings, "mt5_execution_enabled", False):
            reasons.append(MT5_EXECUTION_DISABLED)
        if not getattr(settings, "demo_trading_enabled", False):
            reasons.append(DEMO_TRADING_DISABLED)
        engaged = (getattr(settings, "execution_kill_switch", True)
                   if kill_switch_engaged is None else kill_switch_engaged)
        if engaged:
            reasons.append(KILL_SWITCH_ACTIVE)
        if not demo_account_valid:
            reasons.append(ACCOUNT_NOT_DEMO)
        if not data_quality_ok:
            reasons.append(DATA_QUALITY_FAILED)
        if not risk_approved:
            reasons.append(RISK_BLOCKED)
        return reasons

    def simulate(self, *, symbol: str, signal: SignalAction | str,
                 risk_approved: bool = True, risk_reasons: tuple[str, ...] = (),
                 data_quality_ok: bool = True, demo_account_valid: bool = True,
                 kill_switch_engaged: bool | None = None, confidence: float = 0.0,
                 entry: float | None = None, volume: float | None = None,
                 sl: float | None = None, tp: float | None = None,
                 context: dict[str, Any] | None = None) -> ExecutionSimulation:
        action = SignalAction(str(signal).upper()) if not isinstance(signal, SignalAction) else signal

        if action not in ACTIONABLE:
            return ExecutionSimulation(
                uuid4().hex, symbol.upper(), action, RiskVerdict.NOT_REQUIRED,
                ExecutionVerdict.NOT_APPLICABLE, (NO_ACTIONABLE_SIGNAL,), confidence,
                environment=self.settings.environment,
                observation_mode=bool(getattr(self.settings, "observation_mode", True)),
                context=context or {})

        risk = RiskVerdict.APPROVED if risk_approved else RiskVerdict.BLOCKED
        reasons = self.blocking_reasons(
            risk_approved=risk_approved, data_quality_ok=data_quality_ok,
            demo_account_valid=demo_account_valid, kill_switch_engaged=kill_switch_engaged)
        if not risk_approved:
            reasons.extend(str(item) for item in risk_reasons)

        # Phase 12 never simulates a fill: with observation mode on there is always
        # at least one blocking reason, and the verdict is BLOCKED.
        execution = ExecutionVerdict.BLOCKED if reasons else ExecutionVerdict.SIMULATED
        return ExecutionSimulation(
            uuid4().hex, symbol.upper(), action, risk, execution,
            tuple(dict.fromkeys(reasons)), confidence, entry, volume, sl, tp,
            self.settings.environment,
            bool(getattr(self.settings, "observation_mode", True)),
            context=context or {})
