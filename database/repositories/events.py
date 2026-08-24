from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, TypeVar

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from database.models import LiquidityEvent, StructureEvent


EventModel = TypeVar("EventModel", LiquidityEvent, StructureEvent)


class _EventRepository:
    model: type[EventModel]

    def __init__(self, session: Session):
        self.session = session

    def add(self, values: dict[str, Any]) -> EventModel:
        self._validate_causality(values)
        event_timestamp = values["event_timestamp"]
        row = self.model(timestamp=event_timestamp, **values)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def add_many(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        existing = {
            (
                self._timestamp_key(row.event_timestamp), row.symbol, row.timeframe, row.event_type, row.direction,
                self._price_key(row.price), (row.metadata_json or {}).get("level_type"),
            )
            for row in self.session.scalars(select(self.model))
        }
        models = []
        for values in rows:
            self._validate_causality(values)
            discriminator = (values.get("metadata_json") or {}).get("level_type")
            key = (self._timestamp_key(values["event_timestamp"]), values["symbol"], values["timeframe"], values["event_type"], values.get("direction"), self._price_key(values.get("price")), discriminator)
            if key not in existing:
                models.append(self.model(timestamp=values["event_timestamp"], **values))
                existing.add(key)
        self.session.add_all(models)
        self.session.commit()
        return len(models)

    @staticmethod
    def _price_key(value: Any) -> str | None:
        return None if value is None else str(Decimal(str(value)).normalize())

    @staticmethod
    def _timestamp_key(value: datetime) -> str:
        aware = value if value.tzinfo is not None and value.utcoffset() is not None else value.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _validate_causality(values: dict[str, Any]) -> None:
        confirmation = values.get("confirmation_timestamp")
        if confirmation is not None and values["event_timestamp"] < confirmation:
            raise ValueError("event_timestamp cannot precede confirmation_timestamp")

    def list(
        self, *, symbol: str | None = None, timeframe: str | None = None,
        start: datetime | None = None, end: datetime | None = None,
        offset: int = 0, limit: int = 100,
    ) -> list[EventModel]:
        query: Select[Any] = select(self.model).where(or_(
            self.model.confirmation_timestamp.is_(None),
            self.model.confirmation_timestamp <= self.model.event_timestamp,
        ))
        if symbol:
            query = query.where(self.model.symbol == symbol)
        if timeframe:
            query = query.where(self.model.timeframe == timeframe)
        if start:
            query = query.where(self.model.event_timestamp >= start)
        if end:
            query = query.where(self.model.event_timestamp <= end)
        query = query.order_by(self.model.event_timestamp.desc(), self.model.id.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(query))


class StructureEventRepository(_EventRepository):
    model = StructureEvent


class LiquidityEventRepository(_EventRepository):
    model = LiquidityEvent
