from __future__ import annotations
from dataclasses import asdict
from sqlalchemy.orm import Session
from database.models import PaperAccountRecord,PaperDCAEventRecord,PaperEquitySnapshotRecord,PaperExecutionRecord,PaperOrderRecord,PaperPositionRecord,PaperRiskEventRecord,PaperTradeJournalRecord
from datetime import datetime,timezone
class PaperTradingRepository:
    def __init__(self,session:Session):self.session=session
    @staticmethod
    def _json(value):
        def convert(v):
            if hasattr(v,"isoformat"):return v.isoformat()
            if hasattr(v,"value"):return v.value
            if isinstance(v,dict):return {k:convert(x) for k,x in v.items()}
            if isinstance(v,(list,tuple)):return [convert(x) for x in v]
            return v
        return convert(asdict(value))
    def save_account(self,a):
        self.session.merge(PaperAccountRecord(account_id=a.account_id,initial_balance=a.initial_balance,balance=a.balance,equity=a.equity,margin=a.margin,free_margin=a.free_margin,used_margin=a.used_margin,realized_pnl=a.realized_pnl,unrealized_pnl=a.unrealized_pnl,commission=a.commission,slippage=a.slippage,created_at=a.created_at,updated_at=a.updated_at));self.session.commit()
    def save_position(self,p):self.session.merge(PaperPositionRecord(position_id=p.position_id,symbol=p.symbol,direction=p.direction.value,state=p.state.value,opened_at=p.opened_at,updated_at=p.updated_at,position_json=self._json(p)));self.session.commit()
    def save_order(self,o):self.session.merge(PaperOrderRecord(order_id=o.order_id,position_id=o.position_id,symbol=o.symbol,order_type=o.order_type.value,timestamp=o.timestamp,order_json=self._json(o)));self.session.commit()
    def save_journal(self,j):self.session.merge(PaperTradeJournalRecord(trade_id=j.trade_id,timestamp=j.timestamp,journal_json=self._json(j)));self.session.commit()
    def save_equity(self,a):self.session.add(PaperEquitySnapshotRecord(account_id=a.account_id,timestamp=a.updated_at,equity=a.equity,balance=a.balance,drawdown=a.max_drawdown,snapshot_json=self._json(a)));self.session.commit()
    def save_execution(self,result):
        timestamp=result.order.timestamp if result.order else datetime.now(timezone.utc);self.session.add(PaperExecutionRecord(order_id=result.order.order_id if result.order else None,timestamp=timestamp,accepted=result.accepted,rejection_reason=result.rejection_reason,execution_json=self._json(result)));self.session.commit()
    def save_risk(self,decision,timestamp):self.session.add(PaperRiskEventRecord(timestamp=timestamp,risk_state=decision.risk_state,reason=decision.rejection_reasons[0] if decision.rejection_reasons else None,event_json=self._json(decision)));self.session.commit()
    def save_dca(self,event):self.session.merge(PaperDCAEventRecord(dca_id=event.dca_id,position_id=event.position_id,timestamp=event.timestamp,event_json=self._json(event)));self.session.commit()
