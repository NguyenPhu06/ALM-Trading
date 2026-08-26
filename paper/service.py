from __future__ import annotations
from contextlib import contextmanager
from dataclasses import asdict,replace
from datetime import datetime
from uuid import uuid4
from paper.execution import PaperExecutionEngine
from paper.models import *
from paper.risk import DailyRiskManager,PaperRiskDecision,PaperRiskEngine,validate_model_prediction
from paper.state_machine import PositionStateMachine
from strategy.time_exit import ExitAction


@contextmanager
def bound_repository(service,repository):
    """Bind a repository for the lifetime of one unit of work.

    Sessions are request- or tick-scoped, so the service must not keep a
    repository whose session has since been closed.
    """
    previous=service.repository
    service.repository=repository
    try:yield service
    finally:service.repository=previous

class PaperTradingService:
    def __init__(self,account:PaperAccount|None=None,execution=None,risk=None,repository=None):
        self.account=account or PaperAccount();self.execution=execution or PaperExecutionEngine();self.risk=risk or PaperRiskEngine();self.repository=repository;self.daily=DailyRiskManager();self.state=PaperServiceState.STOPPED;self.positions={};self.orders=[];self.journals=[];self.dca_events=[];self.equity_curve=[];self.machine=PositionStateMachine()
    def start(self):self.state=PaperServiceState.RUNNING;return self.state
    def pause(self):self.state=PaperServiceState.PAUSED;return self.state
    def stop(self):self.state=PaperServiceState.STOPPED;return self.state
    def enter(self,request:PaperOrderRequest,*,quote,setup_status,risk_decision,data_quality,provider_status,prediction,volatility="NORMAL_VOLATILITY",news_risk="LOW",reasons=(),market_context=None,mtf_context=None,liquidity_context=None,indicator_context=None):
        if self.state is not PaperServiceState.RUNNING:return PaperExecutionResult(False,None,"PAPER_TRADING_NOT_RUNNING",0.,reason_codes=("WHY_REJECTED:SERVICE_STATE",))
        model_valid=validate_model_prediction(prediction);strategy_valid=setup_status=="EXECUTABLE_SIMULATION" and bool(getattr(risk_decision,"risk_allowed",getattr(risk_decision,"allowed",False)))
        spread=float(quote.get("ask",0)-quote.get("bid",0)) if quote else 0.
        gate=self.risk.evaluate(drawdown=self.account.max_drawdown,exposure=sum(p.notional for p in self.positions.values()),quantity=request.quantity,daily_drawdown=self.daily.daily_drawdown,concurrent_positions=len(self.positions),volatility=volatility,spread=spread,news_risk=news_risk,data_quality=data_quality,provider_status=provider_status,model_valid=model_valid,strategy_valid=strategy_valid)
        if self.repository:self.repository.save_risk(gate,request.timestamp)
        if not gate.allowed:
            result=PaperExecutionResult(False,None,gate.rejection_reasons[0],0.,reason_codes=tuple(f"WHY_REJECTED:{r}" for r in gate.rejection_reasons))
            if self.repository:self.repository.save_execution(result)
            return result
        result=self.execution.execute(request,quote=quote,volatility=0.);order=result.order
        if not result.accepted or order is None:return result
        position=PaperPosition.open(request.symbol,request.direction,order.executed_price,request.quantity,request.timestamp,request.stop_loss,request.take_profit)
        position.state=PositionState.WATCHING
        self.transition(position,PositionState.ENTRY_READY);self.transition(position,PositionState.OPEN)
        order=replace(order,position_id=position.position_id);self.positions[position.position_id]=position;self.orders.append(order)
        self.journals.append(TradeJournal(position.position_id,request.timestamp,tuple(reasons) or ("WHY_ENTRY:EXECUTABLE_SIMULATION",),market_context or {},mtf_context or {},liquidity_context or {},indicator_context or {},prediction,asdict(gate),(),None,None));result=replace(result,order=order)
        if self.repository:self.repository.save_account(self.account);self.repository.save_position(position);self.repository.save_order(order);self.repository.save_execution(result);self.repository.save_journal(self.journals[-1])
        return result
    def mark(self,position_id,price,timestamp):
        position=self.positions[position_id];pnl=position.mark(price,timestamp);self.account.mark(sum(p.unrealized_pnl for p in self.positions.values()),timestamp);self.daily.update(timestamp,self.account.equity);self.equity_curve.append({"timestamp":timestamp,"equity":self.account.equity,"drawdown":self.account.max_drawdown})
        if self.repository:self.repository.save_position(position);self.repository.save_account(self.account);self.repository.save_equity(self.account)
        return pnl
    def dca(self,position_id,request,*,quote,market_regime,structure_state,risk_state,data_quality,provider_status,prediction,strategy_valid=True,htf_valid=True,volatility="NORMAL_VOLATILITY",news_risk="LOW"):
        """DCA increases exposure, so it passes the same gates as an entry.

        data_quality, provider_status and prediction are required: a caller must state the
        real state of the world rather than inherit a permissive default.
        """
        position=self.positions[position_id]
        spread=float(quote.get("ask",0)-quote.get("bid",0)) if quote else 0.
        gate=self.risk.evaluate(
            new_entry=False,increases_exposure=True,
            drawdown=self.account.max_drawdown,
            exposure=sum(p.notional for p in self.positions.values()),
            quantity=request.quantity,dca_entries=position.dca_entries,
            daily_drawdown=self.daily.daily_drawdown,
            concurrent_positions=len(self.positions),
            volatility=volatility,spread=spread,news_risk=news_risk,
            data_quality=data_quality,provider_status=provider_status,
            model_valid=validate_model_prediction(prediction),
            strategy_valid=strategy_valid and htf_valid,
        )
        if self.repository:self.repository.save_risk(gate,request.timestamp)
        if not gate.allowed:
            self.transition(position,PositionState.DCA_BLOCKED);self.transition(position,PositionState.OPEN)
            if self.repository:self.repository.save_position(position)
            return PaperExecutionResult(False,None,gate.rejection_reasons[0],0.,reason_codes=tuple(f"WHY_REJECTED:{r}" for r in gate.rejection_reasons))
        result=self.execution.execute(request,quote=quote);order=result.order
        if order:
            self.transition(position,PositionState.DCA_ALLOWED)
            position.add(order.executed_price,order.quantity,request.timestamp);self.orders.append(order)
            self.transition(position,PositionState.OPEN);event=DCAEvent(uuid4().hex,position_id,position.dca_entries,request.timestamp,order.executed_price,order.quantity,"WHY_DCA:CONTEXT_VALID",market_regime,structure_state,risk_state);self.dca_events.append(event)
            if self.repository:self.repository.save_position(position);self.repository.save_order(order);self.repository.save_execution(result);self.repository.save_dca(event)
        return result
    def close_position(self,position_id,*,price,timestamp,reason=("WHY_EXIT:MANUAL_PAPER_COMMAND",)):
        position=self.positions[position_id]
        self.transition(position,PositionState.EXIT_PENDING);self.transition(position,PositionState.CLOSED)
        gross=position.mark(price,timestamp);commission=sum(o.commission for o in self.orders if o.position_id==position_id);slippage=sum(o.slippage*o.quantity for o in self.orders if o.position_id==position_id);net=self.account.realize(gross,commission,slippage,timestamp);position.realized_pnl=net;self.positions.pop(position_id)
        journal=next((j for j in self.journals if j.trade_id==position_id),None);saved=None
        if journal:
            index=self.journals.index(journal)
            # Persist the journal that was just closed, not whichever happens to be last.
            saved=replace(journal,dca_history=tuple(asdict(e) for e in self.dca_events if e.position_id==position_id),exit_reason=tuple(reason),final_result={"gross_pnl":gross,"commission":commission,"slippage":slippage,"net_pnl":net})
            self.journals[index]=saved
        if self.repository:
            self.repository.save_position(position);self.repository.save_account(self.account);self.repository.save_equity(self.account)
            if saved is not None:self.repository.save_journal(saved)
        return position

    # ----------------------------------------------------------------- lifecycle
    def transition(self,position,target):
        """Route every state change through PositionStateMachine.

        Phase 8 constructed the machine and then assigned `position.state`
        directly, so none of its transition rules were ever enforced.
        """
        position.state=self.machine.transition(position.state,target);return position.state

    def evaluate_exit(self,position_id,*,engine,timestamp,structure_valid,regime_valid,risk_allowed,
                      confidence,price,next_even_hour_only=True,reason_codes=()):
        """Apply TimeExitEngine to an open position and act on its decision.

        HOLD leaves the position untouched, REDUCE records the reduce state, and
        EXIT/INVALIDATE close it through the normal close path.
        """
        position=self.positions[position_id]
        decision=engine.evaluate(entry_time=position.opened_at,timestamp=timestamp,structure_valid=structure_valid,
                                 regime_valid=regime_valid,risk_allowed=risk_allowed,confidence=confidence,
                                 drawdown=self.account.max_drawdown,next_even_hour_only=next_even_hour_only)
        if decision.action in {ExitAction.EXIT,ExitAction.INVALIDATE}:
            self.close_position(position_id,price=price,timestamp=timestamp,
                                reason=(*reason_codes,*decision.reason_codes))
        elif decision.action is ExitAction.REDUCE:
            self.transition(position,PositionState.REDUCE);self.transition(position,PositionState.OPEN)
            if self.repository:self.repository.save_position(position)
        return decision

    # --------------------------------------------------------------- persistence
    def restore(self,repository):
        """Rehydrate in-memory paper state from the database after a restart."""
        state=repository.load_state()
        if state.get("account") is not None:self.account=state["account"]
        self.positions={p.position_id:p for p in state.get("positions",())}
        self.orders=list(state.get("orders",()))
        self.journals=list(state.get("journals",()))
        self.dca_events=list(state.get("dca_events",()))
        self.equity_curve=list(state.get("equity_curve",()))
        return self
