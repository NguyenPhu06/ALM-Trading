"""MetaTrader 5 terminal lifecycle.

The `MetaTrader5` Python package only drives a terminal on the same Windows host.
Its absence is a normal, reported condition — never a crash — because the API is
expected to run on Linux/Docker in some deployments. See docs/mt5_windows_bridge.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from config.settings import Settings, get_settings
from execution.mt5.safety import MT5SafetyLock, SafetyDecision

logger = logging.getLogger(__name__)

MT5_TERMINAL_NOT_AVAILABLE = "MT5_TERMINAL_NOT_AVAILABLE"
MT5_PACKAGE_NOT_INSTALLED = "MT5_PACKAGE_NOT_INSTALLED"
MT5_NOT_CONNECTED = "MT5_NOT_CONNECTED"
MT5_LOGIN_FAILED = "MT5_LOGIN_FAILED"
MT5_CREDENTIALS_MISSING = "MT5_CREDENTIALS_MISSING"


class MT5ConnectionError(RuntimeError):
    """Base for terminal problems. Carries a stable machine-readable code."""

    code = "MT5_CONNECTION_ERROR"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class MT5TerminalUnavailable(MT5ConnectionError):
    code = MT5_TERMINAL_NOT_AVAILABLE


class ConnectionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTED = "CONNECTED"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class TerminalInfo:
    available: bool
    initialized: bool
    connected: bool
    name: str | None = None
    company: str | None = None
    path: str | None = None
    build: int | None = None


@dataclass(frozen=True, slots=True)
class ConnectionReport:
    state: ConnectionState
    timestamp: datetime
    code: str
    reasons: tuple[str, ...] = ()
    terminal: TerminalInfo | None = None
    server: str | None = None
    masked_login: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def load_mt5_module() -> Any | None:
    """Import MetaTrader5 if this host has it. Returns None instead of raising."""
    try:
        import MetaTrader5  # type: ignore
    except Exception as error:  # ImportError on Linux, OSError on a broken install
        logger.info("MetaTrader5 package unavailable: %s", error)
        return None
    return MetaTrader5


class MT5Connection:
    """Owns initialize/login/shutdown against a local terminal.

    Nothing here can place an order: the wrapper never calls order_send and the
    safety lock is asserted before initialize is even attempted.
    """

    def __init__(self, settings: Settings | None = None, *, module: Any | None = None,
                 safety: MT5SafetyLock | None = None):
        self.settings = settings or get_settings()
        self.safety = safety or MT5SafetyLock(self.settings)
        self._module = module if module is not None else load_mt5_module()
        self._state = ConnectionState.DISCONNECTED
        self._last_report: ConnectionReport | None = None

    # ------------------------------------------------------------------ helpers
    @property
    def module(self) -> Any | None:
        return self._module

    @property
    def state(self) -> ConnectionState:
        return self._state

    def package_available(self) -> bool:
        return self._module is not None

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _report(self, state, code, *, reasons=(), terminal=None, details=None) -> ConnectionReport:
        self._state = state
        report = ConnectionReport(
            state, self._now(), code, tuple(reasons), terminal,
            server=getattr(self.settings, "mt5_server", None),
            masked_login=mask_login(getattr(self.settings, "mt5_login", None)),
            details=details or {},
        )
        self._last_report = report
        return report

    def terminal_info(self) -> TerminalInfo:
        if self._module is None:
            return TerminalInfo(False, False, False)
        try:
            info = self._module.terminal_info()
        except Exception:
            return TerminalInfo(False, False, False)
        if info is None:
            return TerminalInfo(True, False, False)
        return TerminalInfo(
            True, True, bool(getattr(info, "connected", False)),
            name=getattr(info, "name", None), company=getattr(info, "company", None),
            path=getattr(info, "path", None), build=getattr(info, "build", None),
        )

    # -------------------------------------------------------------- lifecycle
    def connect(self) -> ConnectionReport:
        """Initialize the terminal read-only. Never raises for an absent terminal."""
        decision: SafetyDecision = self.safety.evaluate_connection()
        if not decision.allowed:
            logger.error("MT5 connection blocked: %s", ", ".join(decision.reasons))
            return self._report(ConnectionState.BLOCKED, str(decision.block), reasons=decision.reasons)

        if self._module is None:
            return self._report(ConnectionState.UNAVAILABLE, MT5_PACKAGE_NOT_INSTALLED,
                                reasons=(MT5_PACKAGE_NOT_INSTALLED,), terminal=TerminalInfo(False, False, False))

        kwargs: dict[str, Any] = {}
        if self.settings.mt5_terminal_path:
            kwargs["path"] = self.settings.mt5_terminal_path
        if self.settings.mt5_credentials_present():
            kwargs.update(
                login=int(self.settings.mt5_login),
                password=self.settings.mt5_password.get_secret_value(),
                server=self.settings.mt5_server,
                timeout=int(self.settings.mt5_timeout_ms),
            )

        try:
            initialized = bool(self._module.initialize(**kwargs))
        except Exception as error:
            # The password lives in kwargs; log the type only, never the arguments.
            logger.exception("MT5 initialize raised %s", type(error).__name__)
            return self._report(ConnectionState.ERROR, MT5_TERMINAL_NOT_AVAILABLE,
                                reasons=(MT5_TERMINAL_NOT_AVAILABLE,))

        if not initialized:
            reason = self._last_error_code()
            return self._report(ConnectionState.UNAVAILABLE, MT5_TERMINAL_NOT_AVAILABLE,
                                reasons=(MT5_TERMINAL_NOT_AVAILABLE, reason))

        terminal = self.terminal_info()
        if not terminal.connected:
            return self._report(ConnectionState.DISCONNECTED, MT5_NOT_CONNECTED,
                                reasons=(MT5_NOT_CONNECTED,), terminal=terminal)
        return self._report(ConnectionState.CONNECTED, "CONNECTED", terminal=terminal)

    def _last_error_code(self) -> str:
        try:
            code, _ = self._module.last_error()
            return f"MT5_ERROR_{code}"
        except Exception:
            return "MT5_ERROR_UNKNOWN"

    def disconnect(self) -> ConnectionReport:
        if self._module is not None:
            try:
                self._module.shutdown()
            except Exception:
                logger.exception("MT5 shutdown failed")
        return self._report(ConnectionState.DISCONNECTED, "DISCONNECTED")

    def is_connected(self) -> bool:
        if self._module is None:
            return False
        return self.terminal_info().connected

    @property
    def last_report(self) -> ConnectionReport | None:
        return self._last_report


def mask_login(login: Any) -> str | None:
    """Show only the final digits so a dashboard can identify the account safely."""
    if login in (None, ""):
        return None
    text = str(login)
    if len(text) <= 4:
        return "*" * len(text)
    return f"{'*' * (len(text) - 4)}{text[-4:]}"
