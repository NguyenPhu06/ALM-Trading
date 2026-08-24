from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from database.models import MarketIntelligenceSnapshot


class MarketIntelligenceRepository:
    KEY = ("symbol", "timeframe", "event_timestamp", "calculation_version")

    def __init__(self, session: Session):
        self.session = session

    def upsert(self, values: dict[str, Any]) -> MarketIntelligenceSnapshot:
        table = MarketIntelligenceSnapshot.__table__
        dialect = self.session.get_bind().dialect.name
        insert_fn = postgresql_insert if dialect == "postgresql" else sqlite_insert if dialect == "sqlite" else None
        try:
            if insert_fn:
                statement = insert_fn(table).values(values)
                statement = statement.on_conflict_do_update(
                    index_elements=list(self.KEY),
                    set_={
                        "market_candle_id": statement.excluded.market_candle_id,
                        "bias": statement.excluded.bias,
                        "trade_state": statement.excluded.trade_state,
                        "snapshot_json": statement.excluded.snapshot_json,
                        "feature_vector_json": statement.excluded.feature_vector_json,
                    },
                )
                self.session.execute(statement)
            else:
                self.session.add(MarketIntelligenceSnapshot(**values))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return self.session.scalar(select(MarketIntelligenceSnapshot).where(
            MarketIntelligenceSnapshot.symbol == values["symbol"],
            MarketIntelligenceSnapshot.timeframe == values["timeframe"],
            MarketIntelligenceSnapshot.event_timestamp == values["event_timestamp"],
            MarketIntelligenceSnapshot.calculation_version == values["calculation_version"],
        ))

    def list(
        self, *, symbol: str, timeframe: str | None = None,
        start: datetime | None = None, end: datetime | None = None,
        offset: int = 0, limit: int = 100,
    ) -> list[MarketIntelligenceSnapshot]:
        query = select(MarketIntelligenceSnapshot).where(MarketIntelligenceSnapshot.symbol == symbol)
        if timeframe:
            query = query.where(MarketIntelligenceSnapshot.timeframe == timeframe)
        if start:
            query = query.where(MarketIntelligenceSnapshot.event_timestamp >= start)
        if end:
            query = query.where(MarketIntelligenceSnapshot.event_timestamp <= end)
        return list(self.session.scalars(
            query.order_by(MarketIntelligenceSnapshot.event_timestamp.desc()).offset(offset).limit(limit)
        ))
