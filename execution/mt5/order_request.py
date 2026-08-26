"""The order request contract.

A request is inert data. Building one sends nothing: only ExecutionGuard can
authorise it and only MT5ExecutionClient can transmit it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    # Pending types are declared for the contract but Phase 11 sends MARKET only.
    LIMIT = "LIMIT"
    STOP = "STOP"


class ExecutionIntent(StrEnum):
    """What the request is for. DCA is counted against its own limit."""

    NEW_ENTRY = "NEW_ENTRY"
    DCA = "DCA"
    MANUAL_TEST = "MANUAL_TEST"


@dataclass(frozen=True, slots=True)
class OrderRequest:
    symbol: str
    side: OrderSide
    volume: float
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    sl: float | None = None
    tp: float | None = None
    comment: str = "ALM-DEMO"
    strategy_id: str | None = None
    signal_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_id: str = field(default_factory=lambda: uuid4().hex)
    intent: ExecutionIntent = ExecutionIntent.MANUAL_TEST
    magic_number: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "symbol": self.symbol, "side": str(self.side),
            "volume": self.volume, "order_type": str(self.order_type), "price": self.price,
            "sl": self.sl, "tp": self.tp, "comment": self.comment,
            "strategy_id": self.strategy_id, "signal_id": self.signal_id,
            "timestamp": self.timestamp, "intent": str(self.intent),
            "magic_number": self.magic_number,
        }
