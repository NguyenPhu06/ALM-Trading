"""Reconcile what we asked for, what MT5 reported, and what the position shows.

Reconciliation is read-only and never corrects anything: a mismatch is reported
and alerted, never silently repaired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from config.settings import load_yaml
from execution.mt5.order_request import OrderRequest
from execution.mt5.order_result import ExecutionStatus, OrderResult

RECONCILIATION_FAILED = "RECONCILIATION_FAILED"


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    MISMATCHED = "MISMATCHED"
    POSITION_MISSING = "POSITION_MISSING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class ReconciliationRecord:
    request_id: str
    status: ReconciliationStatus
    broker_ticket: int | None = None
    symbol: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    differences: dict[str, Any] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def matched(self) -> bool:
        return self.status is ReconciliationStatus.MATCHED

    def as_dict(self) -> dict[str, Any]:
        return {"request_id": self.request_id, "status": str(self.status),
                "broker_ticket": self.broker_ticket, "symbol": self.symbol,
                "checks": dict(self.checks), "differences": dict(self.differences),
                "reasons": list(self.reasons), "timestamp": self.timestamp}


class Reconciler:
    def __init__(self, *, volume_tolerance: float | None = None,
                 price_tolerance: float | None = None):
        config = load_yaml().get("phase_11", {}).get("reconciliation", {})
        self.volume_tolerance = float(
            volume_tolerance if volume_tolerance is not None else config.get("volume_tolerance", 0.0001))
        self.price_tolerance = float(
            price_tolerance if price_tolerance is not None else config.get("price_tolerance", 0.0010))

    def reconcile(self, request: OrderRequest, result: OrderResult,
                  position: Any | None = None) -> ReconciliationRecord:
        """Compare ticket, volume, price, position, PnL, SL and TP."""
        if result.status in {ExecutionStatus.BLOCKED, ExecutionStatus.REJECTED,
                             ExecutionStatus.FAILED}:
            return ReconciliationRecord(
                request.request_id, ReconciliationStatus.NOT_APPLICABLE,
                symbol=request.symbol, reasons=("ORDER_NOT_EXECUTED",),
                checks={"executed": False})

        checks: dict[str, bool] = {}
        differences: dict[str, Any] = {}
        reasons: list[str] = []

        checks["ticket"] = result.broker_ticket is not None
        if not checks["ticket"]:
            reasons.append("MISSING_BROKER_TICKET")

        volume_delta = abs(result.filled_volume - request.volume)
        checks["volume"] = volume_delta <= self.volume_tolerance
        if not checks["volume"]:
            differences["volume"] = round(volume_delta, 8)
            reasons.append("VOLUME_MISMATCH")

        if request.price is not None and result.filled_price is not None:
            price_delta = abs(result.filled_price - request.price)
            checks["price"] = price_delta <= self.price_tolerance
            if not checks["price"]:
                differences["price"] = round(price_delta, 8)
                reasons.append("PRICE_DEVIATION")
        else:
            checks["price"] = result.filled_price is not None
            if not checks["price"]:
                reasons.append("MISSING_FILL_PRICE")

        if position is None:
            checks["position"] = False
            reasons.append("POSITION_MISSING")
            status = ReconciliationStatus.POSITION_MISSING
            return ReconciliationRecord(
                request.request_id, status, result.broker_ticket, request.symbol,
                checks, differences, tuple(reasons))

        checks["position"] = True
        position_volume = float(getattr(position, "volume", 0.0))
        position_delta = abs(position_volume - result.filled_volume)
        checks["position_volume"] = position_delta <= self.volume_tolerance
        if not checks["position_volume"]:
            differences["position_volume"] = round(position_delta, 8)
            reasons.append("POSITION_VOLUME_MISMATCH")

        ticket_matches = getattr(position, "ticket", None) == result.broker_ticket
        checks["position_ticket"] = bool(ticket_matches)
        if not ticket_matches:
            differences["position_ticket"] = getattr(position, "ticket", None)
            reasons.append("POSITION_TICKET_MISMATCH")

        checks["pnl"] = getattr(position, "profit", None) is not None
        if not checks["pnl"]:
            reasons.append("PNL_UNAVAILABLE")
        else:
            differences["pnl"] = float(getattr(position, "profit", 0.0))

        for name, requested in (("sl", request.sl), ("tp", request.tp)):
            actual = getattr(position, "stop_loss" if name == "sl" else "take_profit", None)
            if requested is None:
                checks[name] = True
                continue
            if actual is None:
                checks[name] = False
                reasons.append(f"{name.upper()}_NOT_SET")
                continue
            delta = abs(float(actual) - float(requested))
            checks[name] = delta <= self.price_tolerance
            if not checks[name]:
                differences[name] = round(delta, 8)
                reasons.append(f"{name.upper()}_MISMATCH")

        status = ReconciliationStatus.MATCHED if all(checks.values()) else ReconciliationStatus.MISMATCHED
        return ReconciliationRecord(
            request.request_id, status, result.broker_ticket, request.symbol,
            checks, differences, tuple(reasons))
