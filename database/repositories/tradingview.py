from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import TradingViewAlert


class TradingViewAlertRepository:
    def __init__(self, session: Session):
        self.session = session

    def add(self, values: dict[str, Any]) -> TradingViewAlert:
        alert = TradingViewAlert(**values)
        self.session.add(alert)
        self.session.commit()
        self.session.refresh(alert)
        return alert

    def list(self, *, symbol: str | None = None, offset: int = 0, limit: int = 100) -> list[TradingViewAlert]:
        query = select(TradingViewAlert)
        if symbol:
            query = query.where(TradingViewAlert.symbol == symbol)
        query = query.order_by(TradingViewAlert.received_at.desc()).offset(offset).limit(limit)
        return list(self.session.scalars(query))

