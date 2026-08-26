"""MT5ExecutionClient — the single component permitted to transmit an order.

It refuses to transmit anything without a matching `GuardDecision`. Passing a
request whose `request_id` does not match the approval, or an approval that was
not approved, raises. Bypassing ExecutionGuard therefore does not work; it is not
a convention, it is enforced here.

DEMO only. There is no live broker adapter and no other broker adapter.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from config.settings import Settings, get_settings
from execution.mt5.account import MT5Account, TradeMode, account_from_mt5
from execution.mt5.connection import MT5Connection
from execution.mt5.execution_guard import GuardDecision
from execution.mt5.order_request import OrderRequest, OrderSide, OrderType
from execution.mt5.order_result import ExecutionStatus, OrderResult, RejectionReason
from execution.mt5.positions import PositionReader

logger = logging.getLogger(__name__)

# MetaTrader5 constants, kept literal so the module imports without the package.
TRADE_ACTION_DEAL = 1
ORDER_TYPE_BUY = 0
ORDER_TYPE_SELL = 1
ORDER_FILLING_IOC = 1
ORDER_TIME_GTC = 0
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010


class ExecutionTransportError(RuntimeError):
    """The terminal could not be reached or refused at transport level."""


class MT5ExecutionClient:
    """DEMO execution adapter. Read helpers mirror the read-only client."""

    def __init__(self, settings: Settings | None = None, *,
                 connection: MT5Connection | None = None,
                 read_client: Any = None):
        self.settings = settings or get_settings()
        self.connection = connection or (read_client.connection if read_client is not None
                                         else MT5Connection(self.settings))
        self.read_client = read_client
        self.positions_reader = PositionReader(alm_magic_number=self.settings.mt5_magic_number)
        self._results: dict[str, OrderResult] = {}

    @property
    def module(self) -> Any | None:
        return self.connection.module

    # ------------------------------------------------------------------ reads
    def get_account(self) -> MT5Account | None:
        if self.module is None:
            return None
        try:
            raw = self.module.account_info()
        except Exception:
            logger.exception("MT5 account_info failed")
            return None
        return account_from_mt5(raw, broker=self.settings.mt5_broker) if raw is not None else None

    def get_position(self, ticket: int) -> Any | None:
        if self.module is None:
            return None
        try:
            rows = self.module.positions_get(ticket=int(ticket))
        except TypeError:
            rows = self.module.positions_get()
        except Exception:
            logger.exception("MT5 positions_get failed")
            return None
        if not rows:
            return None
        canonical = None
        if self.read_client is not None and getattr(self.read_client, "resolver", None):
            canonical = self.read_client.resolver.canonical_for
        positions = self.positions_reader.read(rows, canonical=canonical)
        return next((position for position in positions if position.ticket == int(ticket)), None)

    def get_order_result(self, request_id: str) -> OrderResult | None:
        return self._results.get(request_id)

    @property
    def results(self) -> tuple[OrderResult, ...]:
        return tuple(self._results.values())

    # -------------------------------------------------------------- execution
    def _broker_symbol(self, symbol: str) -> str:
        if self.read_client is not None:
            resolved = self.read_client.resolve_symbol(symbol)
            if resolved.ok:
                return resolved.data.name
        return symbol

    @staticmethod
    def _verify(request: OrderRequest, approval: GuardDecision | None) -> None:
        """No approval, no transmission. This is the enforcement point."""
        if approval is None:
            raise ExecutionTransportError("an ExecutionGuard approval is required to send an order")
        if not approval.approved:
            raise ExecutionTransportError(f"guard refused: {', '.join(approval.reasons)}")
        if approval.request_id != request.request_id:
            raise ExecutionTransportError("guard approval does not match this request")

    def send_market_order(self, request: OrderRequest, approval: GuardDecision | None = None) -> OrderResult:
        """Transmit a DEMO market order. Requires a matching guard approval."""
        self._verify(request, approval)
        if request.order_type is not OrderType.MARKET:
            return OrderResult.blocked_by(request, ("UNSUPPORTED_ORDER_TYPE",),
                                          status=ExecutionStatus.REJECTED)

        # Last line of defence: re-read the account immediately before transmitting.
        account = self.get_account()
        if account is None:
            return self._record(OrderResult.blocked_by(request, (RejectionReason.ACCOUNT_UNAVAILABLE,)))
        if account.trade_mode is TradeMode.REAL:
            logger.error("refusing to transmit: account is REAL")
            return self._record(OrderResult.blocked_by(request, (RejectionReason.ACCOUNT_IS_REAL,)))

        if self.module is None:
            return self._record(OrderResult.blocked_by(
                request, ("MT5_TERMINAL_NOT_AVAILABLE",), status=ExecutionStatus.FAILED))

        payload = {
            "action": TRADE_ACTION_DEAL,
            "symbol": self._broker_symbol(request.symbol),
            "volume": float(request.volume),
            "type": ORDER_TYPE_BUY if request.side is OrderSide.BUY else ORDER_TYPE_SELL,
            "deviation": 20,
            "magic": int(request.magic_number or self.settings.mt5_magic_number or 0),
            "comment": request.comment,
            "type_time": ORDER_TIME_GTC,
            "type_filling": ORDER_FILLING_IOC,
        }
        if request.price is not None:
            payload["price"] = float(request.price)
        if request.sl is not None:
            payload["sl"] = float(request.sl)
        if request.tp is not None:
            payload["tp"] = float(request.tp)

        try:
            raw = self.module.order_send(payload)
        except Exception as error:
            logger.exception("MT5 order_send raised %s", type(error).__name__)
            return self._record(OrderResult(
                request.request_id, ExecutionStatus.FAILED, request.symbol, str(request.side),
                request.volume, error_code="ORDER_SEND_EXCEPTION",
                error_message=type(error).__name__, environment=self.settings.environment))

        return self._record(self._to_result(request, raw))

    def _to_result(self, request: OrderRequest, raw: Any) -> OrderResult:
        if raw is None:
            return OrderResult(
                request.request_id, ExecutionStatus.FAILED, request.symbol, str(request.side),
                request.volume, error_code="NO_RESULT",
                error_message="terminal returned no result", environment=self.settings.environment)
        read = raw.get if isinstance(raw, dict) else (lambda name, default=None: getattr(raw, name, default))
        retcode = int(read("retcode") or 0)
        filled_volume = float(read("volume") or 0.0)
        filled_price = read("price")
        ticket = read("order") or read("deal") or read("ticket")

        if retcode == TRADE_RETCODE_DONE:
            status = ExecutionStatus.FILLED
        elif retcode == TRADE_RETCODE_DONE_PARTIAL:
            status = ExecutionStatus.PARTIAL
        else:
            status = ExecutionStatus.REJECTED
        if status is not ExecutionStatus.REJECTED and filled_volume <= 0:
            status = ExecutionStatus.SUBMITTED

        return OrderResult(
            request.request_id, status, request.symbol, str(request.side), request.volume,
            filled_volume=filled_volume, requested_price=request.price,
            filled_price=float(filled_price) if filled_price else None,
            sl=request.sl, tp=request.tp,
            broker_ticket=int(ticket) if ticket else None,
            error_code=None if status in {ExecutionStatus.FILLED, ExecutionStatus.PARTIAL}
            else f"MT5_RETCODE_{retcode}",
            error_message=str(read("comment") or "") or None,
            environment=self.settings.environment,
        )

    def _record(self, result: OrderResult) -> OrderResult:
        self._results[result.request_id] = result
        return result
