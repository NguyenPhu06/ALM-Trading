"""Read-only pending orders and closed history."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from execution.mt5.positions import PositionOwnership, PositionReader, _epoch_to_utc, parse_direction


@dataclass(frozen=True, slots=True)
class MT5Order:
    ticket: int
    symbol: str
    direction: str
    order_type: str
    volume: float
    price_open: float
    stop_loss: float | None
    take_profit: float | None
    state: str
    time_setup: datetime | None
    magic_number: int
    comment: str
    ownership: PositionOwnership

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket, "symbol": self.symbol, "direction": self.direction,
            "order_type": self.order_type, "volume": self.volume, "price_open": self.price_open,
            "sl": self.stop_loss, "tp": self.take_profit, "state": self.state,
            "time_setup": self.time_setup, "magic_number": self.magic_number,
            "comment": self.comment, "ownership": str(self.ownership),
        }


@dataclass(frozen=True, slots=True)
class MT5Deal:
    ticket: int
    order: int
    symbol: str
    direction: str
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    time: datetime | None
    magic_number: int
    comment: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket, "order": self.order, "symbol": self.symbol,
            "direction": self.direction, "volume": self.volume, "price": self.price,
            "profit": self.profit, "commission": self.commission, "swap": self.swap,
            "time": self.time, "magic_number": self.magic_number, "comment": self.comment,
        }


class HistoryReader:
    """Reads orders and deals. It has no cancel, modify or close capability."""

    def __init__(self, *, reader: PositionReader | None = None):
        self.positions = reader or PositionReader()

    def read_orders(self, rows: Iterable[Any], *, canonical: Any = None) -> list[MT5Order]:
        orders: list[MT5Order] = []
        for row in rows:
            get = row.get if isinstance(row, dict) else (lambda n, d=None: getattr(row, n, d))
            broker_symbol = str(get("symbol") or "")
            magic = int(get("magic") or get("magic_number") or 0)
            comment = str(get("comment") or "")
            stop_loss, take_profit = get("sl"), get("tp")
            orders.append(MT5Order(
                ticket=int(get("ticket") or 0),
                symbol=canonical(broker_symbol) if canonical else broker_symbol.upper(),
                direction=str(parse_direction(get("type"))),
                order_type=str(get("type_description") or get("order_type") or get("type") or ""),
                volume=float(get("volume_current") or get("volume_initial") or get("volume") or 0.0),
                price_open=float(get("price_open") or 0.0),
                stop_loss=float(stop_loss) if stop_loss not in (None, "", 0) else None,
                take_profit=float(take_profit) if take_profit not in (None, "", 0) else None,
                state=str(get("state") or ""),
                time_setup=_epoch_to_utc(get("time_setup") or get("time")),
                magic_number=magic, comment=comment,
                ownership=self.positions.classify(magic, comment),
            ))
        return orders

    def read_deals(self, rows: Iterable[Any], *, canonical: Any = None) -> list[MT5Deal]:
        deals: list[MT5Deal] = []
        for row in rows:
            get = row.get if isinstance(row, dict) else (lambda n, d=None: getattr(row, n, d))
            broker_symbol = str(get("symbol") or "")
            deals.append(MT5Deal(
                ticket=int(get("ticket") or 0), order=int(get("order") or 0),
                symbol=canonical(broker_symbol) if canonical else broker_symbol.upper(),
                direction=str(parse_direction(get("type"))),
                volume=float(get("volume") or 0.0), price=float(get("price") or 0.0),
                profit=float(get("profit") or 0.0), commission=float(get("commission") or 0.0),
                swap=float(get("swap") or 0.0), time=_epoch_to_utc(get("time")),
                magic_number=int(get("magic") or 0), comment=str(get("comment") or ""),
            ))
        return deals

    @staticmethod
    def default_window(days: int = 7, *, now: datetime | None = None) -> tuple[datetime, datetime]:
        end = now or datetime.now(timezone.utc)
        return end - timedelta(days=days), end
