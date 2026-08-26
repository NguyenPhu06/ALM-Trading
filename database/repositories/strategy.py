from __future__ import annotations

from sqlalchemy import desc
from sqlalchemy.orm import Session

from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from database.models import PredictionRecord, StrategyBacktestRecord, StrategyDecisionRecord, StrategyMarketSnapshot, TradeSetupRecord


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

    def latest_prediction(self, symbol: str | None = None):
        query = self.session.query(PredictionRecord)
        if symbol: query = query.filter(PredictionRecord.symbol == symbol.upper())
        return query.order_by(desc(PredictionRecord.timestamp)).first()

    # ------------------------------------------------------------------ writes
    # Phase 6 shipped read-only accessors, so nothing ever populated these tables.
    # The orchestration cycle is the writer; the schema is unchanged.

    def save_snapshot(self, snapshot, *, strategy_version: str, feature_version: str) -> StrategyMarketSnapshot:
        row = StrategyMarketSnapshot(
            timestamp=snapshot.timestamp, symbol=snapshot.symbol.upper(),
            strategy_version=strategy_version, feature_version=feature_version,
            snapshot_json=self.jsonable(snapshot),
        )
        self.session.add(row); self.session.commit(); return row

    def save_setup(self, setup) -> TradeSetupRecord:
        row = TradeSetupRecord(
            setup_id=setup.setup_id, timestamp=setup.timestamp, symbol=setup.symbol.upper(),
            status=str(setup.status.value), direction=str(setup.direction.value),
            score=float(setup.setup_score.score), strategy_version=setup.strategy_version,
            feature_version=setup.feature_version, model_version=setup.model_version,
            setup_json=self.jsonable(setup),
        )
        merged = self.session.merge(row); self.session.commit(); return merged

    def save_decision(self, decision) -> StrategyDecisionRecord:
        row = StrategyDecisionRecord(
            timestamp=decision.timestamp, symbol=decision.symbol.upper(),
            setup_id=decision.setup.setup_id if decision.setup else None,
            decision=decision.decision, strategy_version=decision.strategy_version,
            decision_json=self.jsonable(decision),
        )
        self.session.add(row); self.session.commit(); return row

    def save_prediction(self, prediction) -> PredictionRecord:
        row = PredictionRecord(
            timestamp=prediction.timestamp, symbol=prediction.symbol.upper(),
            model_version=prediction.model_version, feature_version=prediction.feature_version,
            prediction_json=self.jsonable(prediction),
        )
        self.session.add(row); self.session.commit(); return row

    @classmethod
    def jsonable(cls, value: Any) -> Any:
        if is_dataclass(value): return cls.jsonable(asdict(value))
        if isinstance(value, dict): return {str(key): cls.jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)): return [cls.jsonable(item) for item in value]
        if isinstance(value, datetime): return value.isoformat()
        if isinstance(value, Decimal): return float(value)
        if isinstance(value, Enum): return value.value
        return value

