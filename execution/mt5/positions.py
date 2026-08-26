"""Read-only view of MT5 positions.

Positions are classified as ALM or EXTERNAL. Phase 10 touches neither: there is no
modify, close, reverse, hedge or DCA path anywhere in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable

ALM_COMMENT_PREFIX = "ALM"


class PositionOwnership(StrEnum):
    ALM = "ALM"
    EXTERNAL = "EXTERNAL"


class PositionDirection(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    UNKNOWN = "UNKNOWN"


# MetaTrader5 POSITION_TYPE_BUY = 0, POSITION_TYPE_SELL = 1.
DIRECTION_BY_CODE = {0: PositionDirection.LONG, 1: PositionDirection.SHORT}


def parse_direction(value: Any) -> PositionDirection:
    if isinstance(value, PositionDirection):
        return value
    if isinstance(value, int):
        return DIRECTION_BY_CODE.get(value, PositionDirection.UNKNOWN)
    text = str(value or "").strip().upper()
    if text in {"BUY", "LONG"}:
        return PositionDirection.LONG
    if text in {"SELL", "SHORT"}:
        return PositionDirection.SHORT
    return PositionDirection.UNKNOWN


def _epoch_to_utc(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


@dataclass(frozen=True, slots=True)
class MT5Position:
    ticket: int
    symbol: str
    direction: PositionDirection
    volume: float
    open_price: float
    current_price: float
    stop_loss: float | None
    take_profit: float | None
    profit: float
    swap: float
    commission: float
    open_time: datetime | None
    magic_number: int
    comment: str
    ownership: PositionOwnership

    @property
    def is_external(self) -> bool:
        return self.ownership is PositionOwnership.EXTERNAL

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticket": self.ticket, "symbol": self.symbol, "direction": str(self.direction),
            "volume": self.volume, "open_price": self.open_price,
            "current_price": self.current_price, "sl": self.stop_loss, "tp": self.take_profit,
            "profit": self.profit, "swap": self.swap, "commission": self.commission,
            "open_time": self.open_time, "magic_number": self.magic_number,
            "comment": self.comment, "ownership": str(self.ownership),
        }


class PositionReader:
    """Classifies positions by magic number, falling back to the comment prefix.

    A magic number of 0 is MT5's default for manually opened trades, so it is
    never treated as an ALM marker: an unconfigured magic number means every
    position reads as EXTERNAL, which is the safe direction to be wrong in.
    """

    def __init__(self, *, alm_magic_number: int = 0, comment_prefix: str = ALM_COMMENT_PREFIX):
        self.alm_magic_number = int(alm_magic_number or 0)
        self.comment_prefix = comment_prefix

    def classify(self, magic_number: Any, comment: Any) -> PositionOwnership:
        magic = int(magic_number or 0)
        if self.alm_magic_number and magic == self.alm_magic_number:
            return PositionOwnership.ALM
        text = str(comment or "").strip().upper()
        if self.comment_prefix and text.startswith(self.comment_prefix.upper()):
            return PositionOwnership.ALM
        return PositionOwnership.EXTERNAL

    def read(self, rows: Iterable[Any], *, canonical: Any = None) -> list[MT5Position]:
        positions: list[MT5Position] = []
        for row in rows:
            get = row.get if isinstance(row, dict) else (lambda n, d=None: getattr(row, n, d))
            broker_symbol = str(get("symbol") or "")
            symbol = canonical(broker_symbol) if canonical else broker_symbol.upper()
            magic = int(get("magic") or get("magic_number") or 0)
            comment = str(get("comment") or "")
            stop_loss = get("sl")
            take_profit = get("tp")
            positions.append(MT5Position(
                ticket=int(get("ticket") or 0), symbol=symbol,
                direction=parse_direction(get("type")),
                volume=float(get("volume") or 0.0),
                open_price=float(get("price_open") or get("open_price") or 0.0),
                current_price=float(get("price_current") or get("current_price") or 0.0),
                stop_loss=float(stop_loss) if stop_loss not in (None, "", 0) else None,
                take_profit=float(take_profit) if take_profit not in (None, "", 0) else None,
                profit=float(get("profit") or 0.0), swap=float(get("swap") or 0.0),
                commission=float(get("commission") or 0.0),
                open_time=_epoch_to_utc(get("time")),
                magic_number=magic, comment=comment,
                ownership=self.classify(magic, comment),
            ))
        return positions

    @staticmethod
    def summarize(positions: Iterable[MT5Position]) -> dict[str, Any]:
        rows = list(positions)
        return {
            "count": len(rows),
            "alm": sum(not row.is_external for row in rows),
            "external": sum(row.is_external for row in rows),
            "volume": round(sum(row.volume for row in rows), 8),
            "profit": round(sum(row.profit for row in rows), 8),
            "symbols": sorted({row.symbol for row in rows}),
        }
