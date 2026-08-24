from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from data_quality.validator import timeframe_delta
from database.models import MarketCandle
from database.repositories import CandleRepository


class BacktestDataLoader:
    """Loads only candles that were closed and observable at the requested cutoff."""

    def __init__(self, session: Session):
        self.session = session

    def load(
        self, symbol: str, timeframe: str, *, start: datetime | None = None,
        end: datetime | None = None, as_of: datetime | None = None,
        source: str | None = None, limit: int | None = None,
    ) -> list[MarketCandle]:
        cutoff = self._aware(as_of) if as_of else None
        query_end = min(self._aware(end), cutoff) if end and cutoff else end or cutoff
        rows = CandleRepository(self.session).chronological(
            symbol=symbol.upper(), timeframe=timeframe.upper(), start=start,
            end=query_end, source=source, closed_only=True, limit=limit,
        )
        if cutoff is None:
            return rows
        delta = timeframe_delta(timeframe.upper())
        return [row for row in rows if self._aware(row.timestamp) + delta <= cutoff]

    @staticmethod
    def _aware(timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)
