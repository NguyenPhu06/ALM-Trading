"""Phase 10 safety lock.

MetaTrader 5 is a DATA PROVIDER in this phase, never an execution provider.
The lock is evaluated before a connection is opened and again before any data is
read, so a configuration drift cannot silently re-enable trading behaviour.

Configuration is never repaired automatically: a wrong flag blocks, it does not
get corrected.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from config.settings import Settings, get_settings


class ReadOnlyModeError(RuntimeError):
    """Raised when an execution capability is requested in read-only mode."""


class SafetyBlock(StrEnum):
    BLOCK_CONNECTION = "BLOCK_CONNECTION"
    BLOCK_DATA_ACCESS = "BLOCK_DATA_ACCESS"


# Method names an execution provider would expose. Phase 10 has none of them.
FORBIDDEN_EXECUTION_METHODS = (
    "send_order", "modify_order", "close_position", "open_position", "place_dca",
    "order_send", "order_check", "position_close", "position_modify", "set_sl_tp",
)


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    allowed: bool
    block: SafetyBlock | None
    reasons: tuple[str, ...]

    @property
    def code(self) -> str:
        return "ALLOWED" if self.allowed else str(self.block)


class MT5SafetyLock:
    """Evaluates the Phase 10 configuration invariants.

    `Settings` already refuses to construct with an unsafe flag, so in a running
    process these checks are a second line of defence: they also cover a Settings
    object built or mutated in memory.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _violations(self) -> list[str]:
        settings = self.settings
        reasons: list[str] = []
        if str(getattr(settings, "trading_environment", "")).strip().upper() != "DEMO":
            reasons.append("TRADING_ENVIRONMENT_NOT_DEMO")
        if getattr(settings, "live_trading_enabled", False):
            reasons.append("LIVE_TRADING_ENABLED")
        if getattr(settings, "demo_trading_enabled", False):
            reasons.append("DEMO_TRADING_ENABLED")
        if not getattr(settings, "read_only_mode", False):
            reasons.append("READ_ONLY_MODE_DISABLED")
        if not getattr(settings, "mt5_read_only", False):
            reasons.append("MT5_READ_ONLY_DISABLED")
        if getattr(settings, "mt5_execution_enabled", False):
            reasons.append("MT5_EXECUTION_ENABLED")
        return reasons

    def evaluate_connection(self) -> SafetyDecision:
        reasons = self._violations()
        if reasons:
            return SafetyDecision(False, SafetyBlock.BLOCK_CONNECTION, tuple(reasons))
        return SafetyDecision(True, None, ("READ_ONLY_DEMO",))

    def evaluate_data_access(self) -> SafetyDecision:
        reasons = self._violations()
        if reasons:
            return SafetyDecision(False, SafetyBlock.BLOCK_DATA_ACCESS, tuple(reasons))
        return SafetyDecision(True, None, ("READ_ONLY_DEMO",))

    def assert_connection_allowed(self) -> SafetyDecision:
        decision = self.evaluate_connection()
        if not decision.allowed:
            raise ReadOnlyModeError(f"{decision.block}: {', '.join(decision.reasons)}")
        return decision

    def assert_data_access_allowed(self) -> SafetyDecision:
        decision = self.evaluate_data_access()
        if not decision.allowed:
            raise ReadOnlyModeError(f"{decision.block}: {', '.join(decision.reasons)}")
        return decision

    @staticmethod
    def refuse_execution(operation: str) -> None:
        raise ReadOnlyModeError(f"{operation} is unavailable: MT5 is read-only in Phase 10")


class ReadOnlyExecutionGuard:
    """Only for an adapter that must satisfy a broader execution interface.

    Every method refuses. `MT5ReadOnlyClient` deliberately does NOT inherit this:
    it has no execution methods at all, so `hasattr(client, "send_order")` is False.
    """

    def send_order(self, *args, **kwargs):
        MT5SafetyLock.refuse_execution("send_order")

    def modify_order(self, *args, **kwargs):
        MT5SafetyLock.refuse_execution("modify_order")

    def close_position(self, *args, **kwargs):
        MT5SafetyLock.refuse_execution("close_position")

    def open_position(self, *args, **kwargs):
        MT5SafetyLock.refuse_execution("open_position")

    def place_dca(self, *args, **kwargs):
        MT5SafetyLock.refuse_execution("place_dca")
