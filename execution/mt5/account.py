"""Account identity and DEMO/REAL validation.

A REAL account is blocked outright in Phase 10: no data is read from it and no
operation is attempted against it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from execution.mt5.connection import mask_login

ACCOUNT_IS_REAL = "ACCOUNT_IS_REAL"
ACCOUNT_TRADE_MODE_UNKNOWN = "ACCOUNT_TRADE_MODE_UNKNOWN"
ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"


class TradeMode(StrEnum):
    DEMO = "DEMO"
    CONTEST = "CONTEST"
    REAL = "REAL"
    UNKNOWN = "UNKNOWN"


# MetaTrader5 ACCOUNT_TRADE_MODE_* constants.
TRADE_MODE_BY_CODE = {0: TradeMode.DEMO, 1: TradeMode.CONTEST, 2: TradeMode.REAL}


def parse_trade_mode(value: Any) -> TradeMode:
    if isinstance(value, TradeMode):
        return value
    if isinstance(value, bool):
        return TradeMode.UNKNOWN
    if isinstance(value, int):
        return TRADE_MODE_BY_CODE.get(value, TradeMode.UNKNOWN)
    text = str(value or "").strip().upper()
    if text in TradeMode.__members__:
        return TradeMode[text]
    return TradeMode.UNKNOWN


@dataclass(frozen=True, slots=True)
class MT5Account:
    login: int | None
    server: str | None
    broker: str
    currency: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    trade_mode: TradeMode
    leverage: int | None = None
    name: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def masked_login(self) -> str | None:
        return mask_login(self.login)

    @property
    def environment(self) -> str:
        return "DEMO" if self.trade_mode in {TradeMode.DEMO, TradeMode.CONTEST} else str(self.trade_mode)

    def as_public_dict(self) -> dict[str, Any]:
        """Dashboard/API shape. The raw login and any credential are excluded."""
        return {
            "broker": self.broker, "environment": self.environment, "server": self.server,
            "login": self.masked_login, "trade_mode": str(self.trade_mode),
            "currency": self.currency, "balance": self.balance, "equity": self.equity,
            "margin": self.margin, "free_margin": self.free_margin,
            "margin_level": self.margin_level, "leverage": self.leverage,
            "name": self.name, "timestamp": self.timestamp,
        }


@dataclass(frozen=True, slots=True)
class AccountValidation:
    allowed: bool
    trade_mode: TradeMode
    reasons: tuple[str, ...]

    @property
    def blocked(self) -> bool:
        return not self.allowed


class AccountValidator:
    """DEMO and CONTEST are permitted. REAL and UNKNOWN are refused."""

    ALLOWED_MODES = (TradeMode.DEMO, TradeMode.CONTEST)

    def validate(self, account: MT5Account | None) -> AccountValidation:
        if account is None:
            return AccountValidation(False, TradeMode.UNKNOWN, (ACCOUNT_UNAVAILABLE,))
        if account.trade_mode is TradeMode.REAL:
            return AccountValidation(False, TradeMode.REAL, (ACCOUNT_IS_REAL,))
        if account.trade_mode not in self.ALLOWED_MODES:
            return AccountValidation(False, account.trade_mode, (ACCOUNT_TRADE_MODE_UNKNOWN,))
        return AccountValidation(True, account.trade_mode, ("ACCOUNT_IS_DEMO",))


def account_from_mt5(raw: Any, *, broker: str = "Exness") -> MT5Account:
    """Map a MetaTrader5 AccountInfo namedtuple (or a mapping) onto MT5Account."""
    read = raw.get if isinstance(raw, dict) else (lambda name, default=None: getattr(raw, name, default))
    return MT5Account(
        login=read("login"), server=read("server"), broker=broker,
        currency=str(read("currency") or ""),
        balance=float(read("balance") or 0.0), equity=float(read("equity") or 0.0),
        margin=float(read("margin") or 0.0), free_margin=float(read("margin_free") or read("free_margin") or 0.0),
        margin_level=float(read("margin_level") or 0.0),
        trade_mode=parse_trade_mode(read("trade_mode")),
        leverage=read("leverage"), name=read("name"),
    )
