"""Execution modes (section 3).

Six modes, declared explicitly, with OBSERVATION as the shipped default:

* OBSERVATION           — calculate everything, send nothing
* SHADOW                — the DEMO pipeline exactly, minus the broker call
* PAPER                 — simulate a fill in the paper engine, send nothing
* DEMO_MANUAL_APPROVAL  — build a proposal and wait for a human
* DEMO_AUTOMATED        — submit once every gate passes
* LIVE_DISABLED         — the permanent marker that live is off

There is no implicit switching. The mode is whatever configuration says it is;
a closed gate blocks the *order*, it never quietly demotes the *mode*. That
distinction matters: an operator who set DEMO_AUTOMATED and sees orders being
blocked is looking at a gate problem, not at a system that changed its mind.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from config.settings import Settings, get_settings, load_yaml


class ExecutionMode(StrEnum):
    OBSERVATION = "OBSERVATION"
    # Phase 17. SHADOW runs the identical pipeline to DEMO and stops one step
    # short of the wire: same market data, features, inference, strategy, risk
    # and execution proposal, no broker order.
    SHADOW = "SHADOW"
    PAPER = "PAPER"
    DEMO_MANUAL_APPROVAL = "DEMO_MANUAL_APPROVAL"
    DEMO_AUTOMATED = "DEMO_AUTOMATED"
    LIVE_DISABLED = "LIVE_DISABLED"


DEFAULT_MODE = ExecutionMode.OBSERVATION

# The only two modes that may reach a broker. Both are DEMO-only.
BROKER_MODES = frozenset({ExecutionMode.DEMO_MANUAL_APPROVAL, ExecutionMode.DEMO_AUTOMATED})
# Modes that send nothing anywhere near a broker.
SIMULATION_MODES = frozenset({ExecutionMode.OBSERVATION, ExecutionMode.SHADOW,
                              ExecutionMode.PAPER, ExecutionMode.LIVE_DISABLED})

MODE_NOT_CONFIGURED = "EXECUTION_MODE_NOT_CONFIGURED"
MODE_DOES_NOT_EXECUTE = "MODE_DOES_NOT_EXECUTE"
MANUAL_APPROVAL_REQUIRED = "MANUAL_APPROVAL_REQUIRED"
AUTOMATION_NOT_ENABLED = "DEMO_AUTOMATED_EXECUTION_DISABLED"
LIVE_PERMANENTLY_DISABLED = "LIVE_PERMANENTLY_DISABLED"


@dataclass(frozen=True, slots=True)
class ModeDecision:
    mode: ExecutionMode
    configured: str
    sends_orders: bool
    requires_human_approval: bool
    reasons: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def live_enabled(self) -> bool:
        """Always False. No mode in this system enables live trading."""
        return False

    @property
    def automated(self) -> bool:
        return self.mode is ExecutionMode.DEMO_AUTOMATED

    def as_dict(self) -> dict[str, Any]:
        return {"mode": str(self.mode), "configured": self.configured,
                "sends_orders": self.sends_orders,
                "requires_human_approval": self.requires_human_approval,
                "live_enabled": False, "automated": self.automated,
                "reasons": list(self.reasons), "timestamp": self.timestamp}


class UnknownExecutionMode(ValueError):
    """An unrecognised mode string. Never coerced to a default."""


def parse_mode(value: Any) -> ExecutionMode:
    """Strict. An unknown mode is an error, not a silent fallback to OBSERVATION.

    Falling back would be exactly the implicit switching section 3 forbids: a
    typo in DEMO_AUTOMATED must not become a running system in some other mode.
    """
    if isinstance(value, ExecutionMode):
        return value
    text = str(value or "").strip().upper()
    if text in ExecutionMode.__members__:
        return ExecutionMode[text]
    raise UnknownExecutionMode(f"{value!r} is not an execution mode")


class ExecutionModeResolver:
    """Reads the configured mode and states what it permits.

    It answers two questions and nothing else: does this mode send orders, and
    does it need a human first. Whether a *particular* order may be sent is the
    gate chain's decision, not this class's.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        config = load_yaml().get("phase_16", {})
        self.default_mode = parse_mode(config.get("default_mode", DEFAULT_MODE))

    def resolve(self) -> ModeDecision:
        configured = str(getattr(self.settings, "demo_execution_mode", "") or "").strip().upper()
        if not configured:
            # An absent mode is the default, and the default sends nothing.
            return ModeDecision(self.default_mode, "", False, False, (MODE_NOT_CONFIGURED,))

        mode = parse_mode(configured)
        reasons: list[str] = []
        if mode is ExecutionMode.LIVE_DISABLED:
            reasons.append(LIVE_PERMANENTLY_DISABLED)
        if mode in SIMULATION_MODES:
            reasons.append(MODE_DOES_NOT_EXECUTE)
        if mode is ExecutionMode.DEMO_MANUAL_APPROVAL:
            reasons.append(MANUAL_APPROVAL_REQUIRED)
        if mode is ExecutionMode.DEMO_AUTOMATED and not getattr(
                self.settings, "demo_automated_execution_enabled", False):
            # Settings refuses this combination at startup; repeated here for a
            # Settings object built or mutated in memory.
            reasons.append(AUTOMATION_NOT_ENABLED)

        sends = mode in BROKER_MODES and AUTOMATION_NOT_ENABLED not in reasons
        return ModeDecision(mode, configured, sends,
                            mode is ExecutionMode.DEMO_MANUAL_APPROVAL, tuple(reasons))

    @property
    def mode(self) -> ExecutionMode:
        return self.resolve().mode

    def blocking_reasons(self) -> tuple[str, ...]:
        """Why this mode alone would refuse to send an order. Empty when it would not."""
        decision = self.resolve()
        if decision.sends_orders:
            return ()
        return decision.reasons or (MODE_DOES_NOT_EXECUTE,)
