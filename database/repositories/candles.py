from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from database.models import MarketCandle


@dataclass(frozen=True, slots=True)
class CandleUpsertResult:
    inserted: int
    updated: int
    skipped: int
    duplicates_in_batch: int = 0


class CandleRepository:
    KEY_FIELDS = ("symbol", "timeframe", "timestamp", "source")
    VALUE_FIELDS = (
        "open", "high", "low", "close", "volume", "tick_volume", "spread",
        "is_closed", "provider", "provider_timestamp", "source_timeframe",
        "target_timeframe", "resampling_method",
    )

    def __init__(self, session: Session):
        self.session = session

    def add(self, values: dict[str, Any]) -> tuple[MarketCandle | None, bool]:
        result = self.upsert_many([values])
        if result.inserted:
            key = self._key(values)
            return self.session.scalar(select(MarketCandle).where(
                MarketCandle.symbol == key[0], MarketCandle.timeframe == key[1],
                MarketCandle.timestamp == key[2], MarketCandle.source == key[3],
            )), True
        return None, False

    def add_many(self, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
        result = self.upsert_many(rows)
        return result.inserted, result.updated + result.skipped + result.duplicates_in_batch

    def upsert_many(self, rows: Iterable[dict[str, Any]]) -> CandleUpsertResult:
        materialized = list(rows)
        if not materialized:
            return CandleUpsertResult(0, 0, 0, 0)
        unique: dict[tuple[str, str, datetime, str], dict[str, Any]] = {}
        for row in materialized:
            unique[self._key(row)] = row
        duplicates = len(materialized) - len(unique)
        keys = list(unique)
        existing_rows = list(self.session.scalars(select(MarketCandle).where(tuple_(
            MarketCandle.symbol, MarketCandle.timeframe, MarketCandle.timestamp, MarketCandle.source,
        ).in_(keys))))
        existing = {(row.symbol, row.timeframe, self._aware(row.timestamp), row.source): row for row in existing_rows}
        inserts: list[dict[str, Any]] = []
        updates: list[dict[str, Any]] = []
        skipped = 0
        for key, values in unique.items():
            current = existing.get(key)
            if current is None:
                inserts.append(values)
            elif self._changed(current, values):
                updates.append(values)
            else:
                skipped += 1
        changed = inserts + updates
        if changed:
            table = MarketCandle.__table__
            dialect = self.session.get_bind().dialect.name
            insert_fn = postgresql_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
            try:
                if insert_fn is not None:
                    statement = insert_fn(table).values(changed)
                    excluded = statement.excluded
                    statement = statement.on_conflict_do_update(
                        index_elements=list(self.KEY_FIELDS),
                        set_={field: getattr(excluded, field) for field in self.VALUE_FIELDS},
                    )
                    self.session.execute(statement)
                else:
                    for values in changed:
                        self.session.merge(MarketCandle(**values))
                self.session.commit()
            except Exception:
                self.session.rollback()
                raise
        return CandleUpsertResult(len(inserts), len(updates), skipped, duplicates)

    def list(
        self, *, symbol: str | None = None, timeframe: str | None = None,
        start: datetime | None = None, end: datetime | None = None,
        source: str | None = None, closed_only: bool = False,
        offset: int = 0, limit: int = 100,
    ) -> list[MarketCandle]:
        query = self._filtered(symbol=symbol, timeframe=timeframe, start=start, end=end, source=source, closed_only=closed_only)
        query = query.order_by(MarketCandle.timestamp.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(query))

    def latest(
        self, symbol: str, timeframe: str, *, source: str | None = None,
        exclude_sources: tuple[str, ...] = (), as_of: datetime | None = None,
    ) -> MarketCandle | None:
        query = self._filtered(symbol=symbol, timeframe=timeframe, end=as_of, source=source, exclude_sources=exclude_sources)
        return self.session.scalar(query.order_by(MarketCandle.timestamp.desc()).limit(1))

    def chronological(
        self, *, symbol: str, timeframe: str,
        start: datetime | None = None, end: datetime | None = None,
        source: str | None = None, exclude_sources: tuple[str, ...] = (), closed_only: bool = False,
        limit: int | None = None,
    ) -> list[MarketCandle]:
        query = self._filtered(
            symbol=symbol, timeframe=timeframe, start=start, end=end, source=source,
            exclude_sources=exclude_sources, closed_only=closed_only,
        )
        query = query.order_by(MarketCandle.timestamp.asc())
        if limit is not None:
            query = query.limit(limit)
        return list(self.session.scalars(query))

    def recent_chronological(
        self, *, symbol: str, timeframe: str, source: str | None = None,
        exclude_sources: tuple[str, ...] = (), closed_only: bool = False,
        as_of: datetime | None = None, limit: int = 2000,
    ) -> list[MarketCandle]:
        query = self._filtered(
            symbol=symbol, timeframe=timeframe, end=as_of, source=source,
            exclude_sources=exclude_sources, closed_only=closed_only,
        ).order_by(MarketCandle.timestamp.desc()).limit(limit)
        return list(reversed(list(self.session.scalars(query))))

    def count(
        self, *, symbol: str | None = None, timeframe: str | None = None,
        start: datetime | None = None, end: datetime | None = None,
        source: str | None = None, exclude_sources: tuple[str, ...] = (),
    ) -> int:
        query = self._filtered(symbol=symbol, timeframe=timeframe, start=start, end=end, source=source, exclude_sources=exclude_sources)
        return int(self.session.scalar(select(func.count()).select_from(query.subquery())) or 0)

    def recent_timestamps(
        self, symbol: str, timeframe: str, *, exclude_sources: tuple[str, ...] = (), limit: int = 5000,
    ) -> list[datetime]:
        query = select(MarketCandle.timestamp).distinct().where(
            MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe,
        )
        if exclude_sources:
            query = query.where(MarketCandle.source.notin_(exclude_sources))
        query = query.order_by(MarketCandle.timestamp.desc()).limit(limit)
        return list(reversed(list(self.session.scalars(query))))

    @staticmethod
    def _aware(timestamp: datetime) -> datetime:
        return timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)

    @classmethod
    def _key(cls, values: dict[str, Any]) -> tuple[str, str, datetime, str]:
        return (
            str(values["symbol"]), str(values["timeframe"]),
            cls._aware(values["timestamp"]), str(values["source"]),
        )

    @classmethod
    def _changed(cls, current: MarketCandle, values: dict[str, Any]) -> bool:
        for field in cls.VALUE_FIELDS:
            if field not in values:
                continue
            current_value = getattr(current, field)
            incoming = values[field]
            if isinstance(current_value, Decimal) or isinstance(incoming, Decimal):
                if current_value is None or incoming is None:
                    if current_value != incoming:
                        return True
                elif Decimal(str(current_value)) != Decimal(str(incoming)):
                    return True
            elif isinstance(current_value, datetime) and isinstance(incoming, datetime):
                if cls._aware(current_value) != cls._aware(incoming):
                    return True
            elif current_value != incoming:
                return True
        return False

    @staticmethod
    def _filtered(
        *, symbol: str | None = None, timeframe: str | None = None,
        start: datetime | None = None, end: datetime | None = None,
        source: str | None = None, exclude_sources: tuple[str, ...] = (), closed_only: bool = False,
    ):
        query = select(MarketCandle)
        if symbol:
            query = query.where(MarketCandle.symbol == symbol)
        if timeframe:
            query = query.where(MarketCandle.timeframe == timeframe)
        if start:
            query = query.where(MarketCandle.timestamp >= start)
        if end:
            query = query.where(MarketCandle.timestamp <= end)
        if source:
            query = query.where(MarketCandle.source == source)
        if exclude_sources:
            query = query.where(MarketCandle.source.notin_(exclude_sources))
        if closed_only:
            query = query.where(MarketCandle.is_closed.is_(True))
        return query
