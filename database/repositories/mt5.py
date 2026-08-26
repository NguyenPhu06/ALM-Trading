"""Persistence for MT5 read-only observations.

Snapshots are append-only audit rows. Nothing here writes a credential: the
account row stores only a masked login.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Iterable, Sequence

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    MT5AccountRecord,
    MT5AccountSnapshotRecord,
    MT5ConnectionEventRecord,
    MT5DataQualityEventRecord,
    MT5OrderSnapshotRecord,
    MT5PositionSnapshotRecord,
    MT5SymbolSnapshotRecord,
    MT5TickSnapshotRecord,
)

DEFAULT_ACCOUNT_ID = "mt5-demo"
# Never persist anything whose key looks like a secret, whatever the caller passes.
SECRET_KEYS = ("password", "secret", "token", "credential", "api_key")


def scrub(value: Any) -> Any:
    """Recursively drop secret-looking keys and make the payload JSON-safe."""
    if is_dataclass(value):
        return scrub(asdict(value))
    if isinstance(value, dict):
        return {str(key): scrub(item) for key, item in value.items()
                if not any(token in str(key).lower() for token in SECRET_KEYS)}
    if isinstance(value, (list, tuple)):
        return [scrub(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    return value


class MT5Repository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------------ account
    def upsert_account(self, account, *, account_id: str = DEFAULT_ACCOUNT_ID) -> MT5AccountRecord:
        now = datetime.now(timezone.utc)
        row = self.session.get(MT5AccountRecord, account_id)
        values = {
            "login_masked": account.masked_login or "", "broker": account.broker,
            "server": account.server, "currency": account.currency,
            "trade_mode": str(account.trade_mode), "environment": account.environment,
            "leverage": account.leverage, "last_seen": now,
        }
        if row is None:
            row = MT5AccountRecord(account_id=account_id, first_seen=now, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        self.session.commit()
        return row

    def save_account_snapshot(self, account, *, account_id: str = DEFAULT_ACCOUNT_ID) -> MT5AccountSnapshotRecord:
        row = MT5AccountSnapshotRecord(
            timestamp=account.timestamp, account_id=account_id,
            login_masked=account.masked_login or "", broker=account.broker,
            server=account.server, environment=account.environment, currency=account.currency,
            balance=account.balance, equity=account.equity, margin=account.margin,
            free_margin=account.free_margin, margin_level=account.margin_level,
            snapshot_json=scrub(account.as_public_dict()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def latest_account_snapshot(self, account_id: str = DEFAULT_ACCOUNT_ID):
        return (self.session.query(MT5AccountSnapshotRecord)
                .filter(MT5AccountSnapshotRecord.account_id == account_id)
                .order_by(desc(MT5AccountSnapshotRecord.timestamp)).first())

    # ------------------------------------------------------------------ symbols
    def save_symbol_snapshots(self, symbols: Iterable[Any], *, timestamp: datetime | None = None) -> int:
        moment = timestamp or datetime.now(timezone.utc)
        count = 0
        for info in symbols:
            self.session.add(MT5SymbolSnapshotRecord(
                timestamp=moment, symbol=info.canonical or info.normalized,
                broker_symbol=info.name, digits=info.digits, point=info.point,
                spread=float(info.spread) if info.spread is not None else None,
                visible=bool(info.visible), snapshot_json=scrub(info),
            ))
            count += 1
        self.session.commit()
        return count

    # -------------------------------------------------------------------- ticks
    def save_tick(self, tick: dict[str, Any], *, broker_symbol: str | None = None) -> MT5TickSnapshotRecord:
        number = lambda key: float(tick[key]) if tick.get(key) is not None else None
        row = MT5TickSnapshotRecord(
            timestamp=tick["timestamp"], symbol=str(tick["symbol"]), broker_symbol=broker_symbol,
            bid=number("bid"), ask=number("ask"), last=number("last"), spread=number("spread"),
            spread_state=tick.get("spread_state"), source=str(tick.get("source") or "mt5"),
            tick_json=scrub(tick),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def latest_tick(self, symbol: str):
        return (self.session.query(MT5TickSnapshotRecord)
                .filter(MT5TickSnapshotRecord.symbol == symbol.upper())
                .order_by(desc(MT5TickSnapshotRecord.timestamp)).first())

    # ---------------------------------------------------------------- positions
    def save_positions(self, positions: Sequence[Any], *, timestamp: datetime | None = None) -> int:
        moment = timestamp or datetime.now(timezone.utc)
        for position in positions:
            self.session.add(MT5PositionSnapshotRecord(
                timestamp=moment, ticket=position.ticket, symbol=position.symbol,
                direction=str(position.direction), volume=position.volume,
                price=position.current_price or position.open_price, profit=position.profit,
                swap=position.swap, commission=position.commission,
                magic_number=position.magic_number, comment=position.comment,
                ownership=str(position.ownership), position_json=scrub(position.as_dict()),
            ))
        self.session.commit()
        return len(positions)

    def save_orders(self, orders: Sequence[Any], *, timestamp: datetime | None = None) -> int:
        moment = timestamp or datetime.now(timezone.utc)
        for order in orders:
            self.session.add(MT5OrderSnapshotRecord(
                timestamp=moment, ticket=order.ticket, symbol=order.symbol,
                direction=order.direction, order_type=order.order_type, volume=order.volume,
                price_open=order.price_open, state=order.state, magic_number=order.magic_number,
                ownership=str(order.ownership), order_json=scrub(order.as_dict()),
            ))
        self.session.commit()
        return len(orders)

    def latest_positions(self, limit: int = 100):
        return (self.session.query(MT5PositionSnapshotRecord)
                .order_by(desc(MT5PositionSnapshotRecord.timestamp)).limit(limit).all())

    # ------------------------------------------------------------------- events
    def save_connection_event(self, report) -> MT5ConnectionEventRecord:
        row = MT5ConnectionEventRecord(
            timestamp=report.timestamp, state=str(report.state), code=report.code,
            server=report.server, login_masked=report.masked_login,
            reasons=", ".join(report.reasons) if report.reasons else None,
            event_json=scrub({"state": str(report.state), "code": report.code,
                              "reasons": list(report.reasons), "details": report.details}),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def save_data_quality_event(self, report, *, source: str = "mt5") -> MT5DataQualityEventRecord:
        row = MT5DataQualityEventRecord(
            timestamp=report.timestamp, symbol=report.symbol, timeframe=report.timeframe,
            status=str(report.status), reasons=", ".join(report.reasons) if report.reasons else None,
            source=source, report_json=scrub(report),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def recent_quality_events(self, limit: int = 100):
        return (self.session.query(MT5DataQualityEventRecord)
                .order_by(desc(MT5DataQualityEventRecord.timestamp)).limit(limit).all())

    def recent_connection_events(self, limit: int = 100):
        return (self.session.query(MT5ConnectionEventRecord)
                .order_by(desc(MT5ConnectionEventRecord.timestamp)).limit(limit).all())
