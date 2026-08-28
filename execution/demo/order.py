"""The strict DEMO order contract (sections 6 and 12).

A `DemoOrderRequest` carries the whole provenance of a decision: which signal
produced it, which strategy and version, which model and feature version, and
which risk snapshot approved it. That is what makes section 28's audit trail
answerable after the fact rather than a guess.

`request_id` is *derived*, not random. Two submissions of the same signal on the
same trading day produce the same id, which is how section 12's duplicate
blocking works: the second submission is recognised, not merely rate-limited.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from execution.mt5.order_request import ExecutionIntent, OrderRequest, OrderSide, OrderType

MISSING_SIGNAL_ID = "MISSING_SIGNAL_ID"


def execution_request_id(*, signal_id: str, symbol: str, side: Any, intent: Any = ExecutionIntent.NEW_ENTRY,
                         strategy_id: str | None = None, strategy_version: str | None = None,
                         trading_day: date | str | None = None, sequence: int = 0) -> str:
    """Deterministic id for one (signal, symbol, side, intent, day) decision.

    `sequence` exists for a legitimately repeated intent — a second DCA level on
    the same signal is a different order, not a duplicate — and defaults to 0 so
    the ordinary case needs no thought.
    """
    if not str(signal_id or "").strip():
        raise ValueError("a deterministic execution request id needs a signal id")
    day = trading_day.isoformat() if isinstance(trading_day, date) else str(trading_day or "")
    material = "|".join([
        str(signal_id).strip(), str(symbol or "").strip().upper(), str(side),
        str(intent), str(strategy_id or ""), str(strategy_version or ""), day, str(int(sequence)),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class DemoOrderRequest:
    """Section 6, field for field. Building one sends nothing."""

    request_id: str
    symbol: str
    side: OrderSide
    volume: float
    order_type: OrderType = OrderType.MARKET
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_id: str | None = None
    strategy_version: str | None = None
    model_version: str | None = None
    feature_version: str | None = None
    signal_id: str | None = None
    risk_snapshot_id: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""
    intent: ExecutionIntent = ExecutionIntent.NEW_ENTRY
    magic_number: int = 0
    comment: str = "ALM-DEMO"
    # Sizing provenance, so a volume is never an unexplained number.
    risk_percent: float | None = None
    risk_amount: float | None = None
    stop_distance: float | None = None

    @classmethod
    def build(cls, *, symbol: str, side: Any, volume: float, signal_id: str,
              trading_day: date | str | None = None, sequence: int = 0,
              **kwargs: Any) -> "DemoOrderRequest":
        """Build with a derived request id. The id is never supplied by a caller."""
        resolved_side = side if isinstance(side, OrderSide) else OrderSide(str(side).upper())
        intent = kwargs.get("intent", ExecutionIntent.NEW_ENTRY)
        request_id = execution_request_id(
            signal_id=signal_id, symbol=symbol, side=resolved_side, intent=intent,
            strategy_id=kwargs.get("strategy_id"),
            strategy_version=kwargs.get("strategy_version"),
            trading_day=trading_day, sequence=sequence)
        return cls(request_id=request_id, symbol=str(symbol).strip().upper(), side=resolved_side,
                   volume=float(volume), signal_id=str(signal_id), **kwargs)

    @property
    def is_dca(self) -> bool:
        return self.intent is ExecutionIntent.DCA

    def to_order_request(self) -> OrderRequest:
        """Adapt onto the Phase 11 contract that ExecutionGuard and the client speak.

        The two contracts are deliberately separate: Phase 11's is what the wire
        needs, Phase 16's is what the audit trail needs.
        """
        return OrderRequest(
            symbol=self.symbol, side=self.side, volume=self.volume, order_type=self.order_type,
            price=self.price, sl=self.stop_loss, tp=self.take_profit, comment=self.comment,
            strategy_id=self.strategy_id, signal_id=self.signal_id, timestamp=self.timestamp,
            request_id=self.request_id, intent=self.intent, magic_number=self.magic_number,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "symbol": self.symbol, "side": str(self.side),
            "volume": self.volume, "order_type": str(self.order_type), "price": self.price,
            "stop_loss": self.stop_loss, "take_profit": self.take_profit,
            "strategy_id": self.strategy_id, "strategy_version": self.strategy_version,
            "model_version": self.model_version, "feature_version": self.feature_version,
            "signal_id": self.signal_id, "risk_snapshot_id": self.risk_snapshot_id,
            "timestamp": self.timestamp, "reason": self.reason, "intent": str(self.intent),
            "magic_number": self.magic_number, "comment": self.comment,
            "risk_percent": self.risk_percent, "risk_amount": self.risk_amount,
            "stop_distance": self.stop_distance,
        }
