from __future__ import annotations

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import StrategyBacktestRecord, StrategyDecisionRecord, StrategyMarketSnapshot, TradeSetupRecord


class StrategyRepository:
    def __init__(self, session: Session): self.session = session

    def latest_setup(self, symbol: str | None = None):
        query = self.session.query(TradeSetupRecord)
        if symbol: query = query.filter(TradeSetupRecord.symbol == symbol.upper())
        return query.order_by(desc(TradeSetupRecord.timestamp)).first()

    def latest_snapshot(self, symbol: str):
        return self.session.query(StrategyMarketSnapshot).filter(StrategyMarketSnapshot.symbol == symbol.upper()).order_by(desc(StrategyMarketSnapshot.timestamp)).first()

    def latest_decision(self, symbol: str | None = None):
        query = self.session.query(StrategyDecisionRecord)
        if symbol: query = query.filter(StrategyDecisionRecord.symbol == symbol.upper())
        return query.order_by(desc(StrategyDecisionRecord.timestamp)).first()

    def latest_backtest(self):
        return self.session.query(StrategyBacktestRecord).order_by(desc(StrategyBacktestRecord.created_at)).first()

