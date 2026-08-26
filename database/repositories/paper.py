from __future__ import annotations
from dataclasses import asdict
from sqlalchemy.orm import Session
from database.models import PaperAccountRecord,PaperDCAEventRecord,PaperEquitySnapshotRecord,PaperExecutionRecord,PaperOrderRecord,PaperPositionRecord,PaperRiskEventRecord,PaperTradeJournalRecord
from datetime import datetime,timezone
from decimal import Decimal
from paper.models import DCAEvent,Direction,OrderType,PaperAccount,PaperOrder,PaperPosition,PositionState,TradeJournal
class PaperTradingRepository:
    def __init__(self,session:Session):self.session=session
    @staticmethod
    def _json(value):
        def convert(v):
            if hasattr(v,"isoformat"):return v.isoformat()
            if hasattr(v,"value"):return v.value
            if isinstance(v,Decimal):return float(v)
            if isinstance(v,dict):return {str(k):convert(x) for k,x in v.items()}
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

    # ------------------------------------------------------------------ restore
    # Reads back what the save_* methods wrote so paper state survives a restart.
    # No second persistence layer: the same rows, the same tables.

    @staticmethod
    def _time(value):
        if value is None:return None
        if isinstance(value,str):value=datetime.fromisoformat(value)
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    def _position(self,row):
        data=dict(row.position_json or {})
        position=PaperPosition(
            row.position_id,row.symbol,Direction(row.direction),float(data.get("entry_price",0.)),
            float(data.get("average_entry_price",0.)),float(data.get("quantity",0.)),
            float(data.get("notional",0.)),float(data.get("unrealized_pnl",0.)),
            float(data.get("realized_pnl",0.)),self._time(row.opened_at),self._time(row.updated_at),
            PositionState(row.state),int(data.get("dca_entries",0)),
            data.get("stop_loss"),data.get("take_profit"),
        )
        return position

    def _order(self,row):
        data=dict(row.order_json or {})
        return PaperOrder(
            row.order_id,row.position_id,row.symbol,Direction(data["direction"]),OrderType(row.order_type),
            data.get("requested_price"),float(data.get("executed_price",0.)),float(data.get("quantity",0.)),
            float(data.get("slippage",0.)),float(data.get("commission",0.)),self._time(row.timestamp),
            str(data.get("strategy_version","")),data.get("model_version"),
            float(data.get("spread",0.)),str(data.get("spread_source","")),
        )

    def _journal(self,row):
        data=dict(row.journal_json or {})
        return TradeJournal(
            row.trade_id,self._time(row.timestamp),tuple(data.get("entry_reason") or ()),
            data.get("market_context") or {},data.get("mtf_context") or {},
            data.get("liquidity_context") or {},data.get("indicator_context") or {},
            data.get("nn_prediction"),data.get("risk_decision") or {},
            tuple(data.get("dca_history") or ()),
            tuple(data["exit_reason"]) if data.get("exit_reason") else None,
            data.get("final_result"),
        )

    def _dca(self,row):
        data=dict(row.event_json or {})
        return DCAEvent(
            row.dca_id,row.position_id,int(data.get("entry_number",0)),self._time(row.timestamp),
            float(data.get("price",0.)),float(data.get("quantity",0.)),str(data.get("reason","")),
            str(data.get("market_regime","")),str(data.get("structure_state","")),str(data.get("risk_state","")),
        )

    def load_state(self,account_id="paper-default"):
        account_row=self.session.get(PaperAccountRecord,account_id)
        account=None
        if account_row is not None:
            account=PaperAccount(
                account_row.account_id,float(account_row.initial_balance),float(account_row.balance),
                float(account_row.equity),float(account_row.margin),float(account_row.free_margin),
                float(account_row.used_margin),float(account_row.realized_pnl),
                float(account_row.unrealized_pnl),float(account_row.commission),float(account_row.slippage),
                self._time(account_row.created_at),self._time(account_row.updated_at),
            )
        positions=[self._position(r) for r in self.session.query(PaperPositionRecord).order_by(PaperPositionRecord.opened_at).all()]
        equity=[{"timestamp":self._time(r.timestamp),"equity":float(r.equity),"drawdown":float(r.drawdown)}
                for r in self.session.query(PaperEquitySnapshotRecord).order_by(PaperEquitySnapshotRecord.timestamp).all()]
        if account is not None and equity:
            account.peak_equity=max(account.peak_equity,max(row["equity"] for row in equity))
            account.max_drawdown=max(account.max_drawdown,max(row["drawdown"] for row in equity))
        return {
            "account":account,
            # Only still-open positions belong in the live book; closed ones stay in the journal.
            "positions":tuple(p for p in positions if p.state is not PositionState.CLOSED),
            "orders":tuple(self._order(r) for r in self.session.query(PaperOrderRecord).order_by(PaperOrderRecord.timestamp).all()),
            "journals":tuple(self._journal(r) for r in self.session.query(PaperTradeJournalRecord).order_by(PaperTradeJournalRecord.timestamp).all()),
            "dca_events":tuple(self._dca(r) for r in self.session.query(PaperDCAEventRecord).order_by(PaperDCAEventRecord.timestamp).all()),
            "equity_curve":equity,
        }
