from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.models import MarketCandle


class CandleRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, values: dict[str, Any]) -> tuple[MarketCandle | None, bool]:
        candle = MarketCandle(**values)
        self.session.add(candle)
        try:
            self.session.commit()
            self.session.refresh(candle)
            return candle, True
        except IntegrityError:
            self.session.rollback()
            return None, False

    def add_many(self, rows: Iterable[dict[str, Any]]) -> tuple[int, int]:
        inserted = duplicates = 0
        for row in rows:
            _, created = self.add(row)
            if created:
                inserted += 1
            else:
                duplicates += 1
        return inserted, duplicates

    def list(self, *, symbol: str | None = None, timeframe: str | None = None, offset: int = 0, limit: int = 100) -> list[MarketCandle]:
        query = select(MarketCandle)
        if symbol:
            query = query.where(MarketCandle.symbol == symbol)
        if timeframe:
            query = query.where(MarketCandle.timeframe == timeframe)
        query = query.order_by(MarketCandle.timestamp.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(query))

    def latest(self, symbol: str, timeframe: str) -> MarketCandle | None:
        query = select(MarketCandle).where(
            MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe
        ).order_by(MarketCandle.timestamp.desc()).limit(1)
        return self.session.scalar(query)

    def chronological(
        self, *, symbol: str, timeframe: str,
        start: datetime | None = None, end: datetime | None = None,
        closed_only: bool = False,
    ) -> list[MarketCandle]:
        query = select(MarketCandle).where(
            MarketCandle.symbol == symbol, MarketCandle.timeframe == timeframe,
        )
        if start:
            query = query.where(MarketCandle.timestamp >= start)
        if end:
            query = query.where(MarketCandle.timestamp <= end)
        if closed_only:
            query = query.where(MarketCandle.is_closed.is_(True))
        return list(self.session.scalars(query.order_by(MarketCandle.timestamp.asc())))
