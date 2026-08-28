"""DemoAccountValidator — the gate that must clear before any execution capability.

Four explicit outcomes, and only one of them permits anything:

* VALID_DEMO       — verified DEMO/CONTEST account on a recognised DEMO server
* INVALID_ACCOUNT  — a REAL account, or terminal permissions that are unsafe
* UNKNOWN_ACCOUNT  — trade mode or broker/server could not be verified
* CONNECTION_ERROR — no terminal, no connection, no account to inspect

Anything other than VALID_DEMO blocks. Unknown is never treated as safe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from config.settings import Settings, get_settings, load_yaml
from execution.mt5.account import MT5Account, TradeMode
from execution.mt5.connection import TerminalInfo

DEMO_SERVER_PATTERNS = ("demo", "trial", "practice", "test")


class DemoValidation(StrEnum):
    VALID_DEMO = "VALID_DEMO"
    INVALID_ACCOUNT = "INVALID_ACCOUNT"
    UNKNOWN_ACCOUNT = "UNKNOWN_ACCOUNT"
    CONNECTION_ERROR = "CONNECTION_ERROR"


# Reason codes, stable so alerts and the dashboard can key off them.
ACCOUNT_IS_REAL = "ACCOUNT_IS_REAL"
ACCOUNT_TRADE_MODE_UNKNOWN = "ACCOUNT_TRADE_MODE_UNKNOWN"
ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
TERMINAL_UNAVAILABLE = "TERMINAL_UNAVAILABLE"
NOT_CONNECTED = "NOT_CONNECTED"
SERVER_UNVERIFIED = "SERVER_UNVERIFIED"
SERVER_NOT_DEMO = "SERVER_NOT_DEMO"
BROKER_UNVERIFIED = "BROKER_UNVERIFIED"
TERMINAL_API_DISABLED = "TERMINAL_API_DISABLED"
TERMINAL_PERMISSIONS_UNKNOWN = "TERMINAL_PERMISSIONS_UNKNOWN"


@dataclass(frozen=True, slots=True)
class DemoAccountResult:
    status: DemoValidation
    reasons: tuple[str, ...] = ()
    account: MT5Account | None = None
    terminal: TerminalInfo | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def valid(self) -> bool:
        return self.status is DemoValidation.VALID_DEMO

    @property
    def blocked(self) -> bool:
        return not self.valid

    def as_dict(self) -> dict[str, Any]:
        """Safe account information only: never a password, never a raw login."""
        return {
            "status": str(self.status), "valid": self.valid, "reasons": list(self.reasons),
            "timestamp": self.timestamp,
            "account": {
                "login": self.account.masked_login if self.account else None,
                "broker": self.account.broker if self.account else None,
                "server": self.account.server if self.account else None,
                "account_type": str(self.account.trade_mode) if self.account else "UNKNOWN",
                "environment": self.account.environment if self.account else "UNKNOWN",
                "currency": self.account.currency if self.account else None,
                "balance": self.account.balance if self.account else None,
                "equity": self.account.equity if self.account else None,
                "leverage": self.account.leverage if self.account else None,
            },
            "terminal": self.terminal.as_dict() if self.terminal else None,
        }


class DemoAccountValidator:
    """Verifies account type, broker/server and terminal permissions.

    `require_permissions` decides whether unknown terminal permissions block. It
    defaults to False because Phase 12 is observation-only and reading market data
    does not need trade permissions; the execution path sets it True.
    """

    def __init__(self, settings: Settings | None = None, *, require_permissions: bool = False):
        self.settings = settings or get_settings()
        config = load_yaml().get("phase_11", {})
        self.server_patterns = tuple(
            str(item).lower() for item in (config.get("demo_server_patterns") or DEMO_SERVER_PATTERNS))
        self.require_permissions = require_permissions

    def _server_reasons(self, account: MT5Account) -> list[str]:
        server = str(account.server or "").strip()
        if not server:
            return [SERVER_UNVERIFIED]
        if not any(pattern in server.lower() for pattern in self.server_patterns):
            return [SERVER_NOT_DEMO]
        return []

    def _permission_reasons(self, terminal: TerminalInfo | None) -> list[str]:
        if terminal is None or not terminal.permissions_known:
            return [TERMINAL_PERMISSIONS_UNKNOWN] if self.require_permissions else []
        # A terminal with the trading API barred cannot be verified for execution.
        return [TERMINAL_API_DISABLED] if terminal.tradeapi_disabled else []

    def validate(self, account: MT5Account | None, *, terminal: TerminalInfo | None = None,
                 connected: bool | None = None) -> DemoAccountResult:
        # 1. Can we see the terminal at all?
        if terminal is not None and not terminal.available:
            return DemoAccountResult(DemoValidation.CONNECTION_ERROR, (TERMINAL_UNAVAILABLE,),
                                     None, terminal)

        # 2. A REAL account is an outright refusal, and it outranks every other
        #    verdict. The read client disconnects from a REAL account, so checking
        #    connectivity first would report the vaguer CONNECTION_ERROR instead.
        if account is not None and account.trade_mode is TradeMode.REAL:
            return DemoAccountResult(DemoValidation.INVALID_ACCOUNT, (ACCOUNT_IS_REAL,),
                                     account, terminal)

        if connected is False:
            return DemoAccountResult(DemoValidation.CONNECTION_ERROR, (NOT_CONNECTED,),
                                     account, terminal)
        if account is None:
            return DemoAccountResult(DemoValidation.CONNECTION_ERROR, (ACCOUNT_UNAVAILABLE,),
                                     None, terminal)

        # 3. An unverifiable trade mode is unknown, never assumed to be DEMO.
        if account.trade_mode not in {TradeMode.DEMO, TradeMode.CONTEST}:
            return DemoAccountResult(DemoValidation.UNKNOWN_ACCOUNT, (ACCOUNT_TRADE_MODE_UNKNOWN,),
                                     account, terminal)

        reasons: list[str] = []
        if not str(account.broker or "").strip():
            reasons.append(BROKER_UNVERIFIED)
        reasons.extend(self._server_reasons(account))
        if SERVER_NOT_DEMO in reasons:
            # The account claims DEMO but the server does not look like one.
            return DemoAccountResult(DemoValidation.INVALID_ACCOUNT, tuple(reasons), account, terminal)

        permission_reasons = self._permission_reasons(terminal)
        if TERMINAL_API_DISABLED in permission_reasons:
            return DemoAccountResult(DemoValidation.INVALID_ACCOUNT,
                                     tuple(reasons + permission_reasons), account, terminal)
        reasons.extend(permission_reasons)

        if reasons:
            return DemoAccountResult(DemoValidation.UNKNOWN_ACCOUNT, tuple(reasons), account, terminal)
        return DemoAccountResult(DemoValidation.VALID_DEMO, ("ACCOUNT_IS_DEMO",), account, terminal)

    def validate_client(self, client: Any) -> DemoAccountResult:
        """Convenience wrapper around an MT5ReadOnlyClient."""
        if client is None:
            return DemoAccountResult(DemoValidation.CONNECTION_ERROR, (TERMINAL_UNAVAILABLE,))
        terminal = client.connection.terminal_info()
        if not terminal.available:
            return DemoAccountResult(DemoValidation.CONNECTION_ERROR, (TERMINAL_UNAVAILABLE,),
                                     None, terminal)
        result = client.get_account()
        account = result.data if result.ok else getattr(client, "account", None)
        return self.validate(account, terminal=terminal, connected=terminal.connected)
