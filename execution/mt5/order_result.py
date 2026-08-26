"""Order outcomes and the rejection contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class ExecutionStatus(StrEnum):
    REJECTED = "REJECTED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


# Every reason ExecutionGuard can refuse. Stable codes so alerts and the dashboard
# can key off them without parsing prose.
class RejectionReason(StrEnum):
    ENVIRONMENT_NOT_DEMO = "ENVIRONMENT_NOT_DEMO"
    LIVE_TRADING_ENABLED = "LIVE_TRADING_ENABLED"
    DEMO_TRADING_DISABLED = "DEMO_TRADING_DISABLED"
    MT5_EXECUTION_DISABLED = "MT5_EXECUTION_DISABLED"
    MT5_READ_ONLY = "MT5_READ_ONLY"
    KILL_SWITCH_ENGAGED = "KILL_SWITCH_ENGAGED"
    ACCOUNT_IS_REAL = "ACCOUNT_IS_REAL"
    ACCOUNT_UNAVAILABLE = "ACCOUNT_UNAVAILABLE"
    SERVER_NOT_DEMO = "SERVER_NOT_DEMO"
    NOT_CONNECTED = "NOT_CONNECTED"
    RISK_BLOCKED = "RISK_BLOCKED"
    DAILY_DRAWDOWN_EXCEEDED = "DAILY_DRAWDOWN_EXCEEDED"
    MAXIMUM_EXPOSURE = "MAXIMUM_EXPOSURE"
    POSITION_LIMIT = "POSITION_LIMIT"
    DCA_LIMIT = "DCA_LIMIT"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    SESSION_NOT_ALLOWED = "SESSION_NOT_ALLOWED"
    INVALID_SYMBOL = "INVALID_SYMBOL"
    SYMBOL_NOT_ALLOWED = "SYMBOL_NOT_ALLOWED"
    INVALID_VOLUME = "INVALID_VOLUME"
    VOLUME_ABOVE_LIMIT = "VOLUME_ABOVE_LIMIT"
    INVALID_PRICE = "INVALID_PRICE"
    PRICE_DEVIATION = "PRICE_DEVIATION"
    INVALID_STOP_LOSS = "INVALID_STOP_LOSS"
    INVALID_TAKE_PROFIT = "INVALID_TAKE_PROFIT"
    STRATEGY_NOT_EXECUTABLE = "STRATEGY_NOT_EXECUTABLE"
    QUOTE_UNAVAILABLE = "QUOTE_UNAVAILABLE"


class ExecutionRejected(RuntimeError):
    """Raised only by the assert_* helpers; the normal path returns a result."""

    def __init__(self, reasons, message: str | None = None):
        self.reasons = tuple(str(reason) for reason in reasons)
        super().__init__(message or f"execution rejected: {', '.join(self.reasons)}")


@dataclass(frozen=True, slots=True)
class OrderResult:
    request_id: str
    status: ExecutionStatus
    symbol: str
    side: str
    requested_volume: float
    filled_volume: float = 0.0
    requested_price: float | None = None
    filled_price: float | None = None
    sl: float | None = None
    tp: float | None = None
    broker_ticket: int | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    error_code: str | None = None
    error_message: str | None = None
    reasons: tuple[str, ...] = ()
    environment: str = "DEMO"

    @property
    def accepted(self) -> bool:
        return self.status in {ExecutionStatus.FILLED, ExecutionStatus.PARTIAL,
                               ExecutionStatus.SUBMITTED}

    @property
    def blocked(self) -> bool:
        return self.status in {ExecutionStatus.BLOCKED, ExecutionStatus.REJECTED}

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "status": str(self.status), "symbol": self.symbol,
            "side": self.side, "requested_volume": self.requested_volume,
            "filled_volume": self.filled_volume, "requested_price": self.requested_price,
            "filled_price": self.filled_price, "sl": self.sl, "tp": self.tp,
            "broker_ticket": self.broker_ticket, "timestamp": self.timestamp,
            "error_code": self.error_code, "error_message": self.error_message,
            "reasons": list(self.reasons), "environment": self.environment,
        }

    @classmethod
    def blocked_by(cls, request, reasons, *, status: ExecutionStatus = ExecutionStatus.BLOCKED,
                   environment: str = "DEMO") -> "OrderResult":
        codes = tuple(str(reason) for reason in reasons)
        return cls(
            request.request_id, status, request.symbol, str(request.side), request.volume,
            requested_price=request.price, sl=request.sl, tp=request.tp,
            error_code=codes[0] if codes else None,
            error_message="; ".join(codes) or None, reasons=codes, environment=environment,
        )
