from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from database.models import SimulatedTradeRecord

if TYPE_CHECKING:
    from backtest.contracts import SimulatedTrade


class SimulatedTradeRepository:
    def __init__(self, session: Session):
        self.session = session

    @staticmethod
    def _jsonable(items: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
        return [
            {key: value.isoformat() if isinstance(value, datetime) else value for key, value in item.items()}
            for item in items
        ]

    def add(self, trade: "SimulatedTrade") -> SimulatedTradeRecord:
        row = SimulatedTradeRecord(
            entry_time=trade.entry_time, entry_price=trade.entry_price,
            exit_time=trade.exit_time, exit_price=trade.exit_price,
            direction=trade.direction.value, size=trade.size, pnl=trade.pnl,
            drawdown=trade.drawdown, reason=trade.reason,
            counter_trend_trade=trade.counter_trend_trade,
            entries_json=self._jsonable(trade.entries),
            evaluations_json=self._jsonable(trade.evaluations),
        )
        try:
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            return row
        except Exception:
            self.session.rollback()
            raise
