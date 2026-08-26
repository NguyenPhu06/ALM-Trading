from __future__ import annotations
from dataclasses import dataclass,field
from datetime import datetime,timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

class Direction(StrEnum):LONG="LONG";SHORT="SHORT"
class OrderType(StrEnum):MARKET="MARKET";LIMIT="LIMIT";DCA="DCA";REDUCE="REDUCE";CLOSE="CLOSE"
class PositionState(StrEnum):WATCHING="WATCHING";ENTRY_READY="ENTRY_READY";OPEN="OPEN";DCA_ALLOWED="DCA_ALLOWED";DCA_BLOCKED="DCA_BLOCKED";REDUCE="REDUCE";EXIT_PENDING="EXIT_PENDING";CLOSED="CLOSED";INVALIDATED="INVALIDATED"
class TradingEnvironment(StrEnum):PAPER="PAPER";LIVE="LIVE"
class PaperServiceState(StrEnum):STOPPED="STOPPED";RUNNING="RUNNING";PAUSED="PAUSED"

@dataclass(slots=True)
class PaperAccount:
    account_id:str="paper-default";initial_balance:float=1000.;balance:float=1000.;equity:float=1000.;margin:float=0.;free_margin:float=1000.;used_margin:float=0.;realized_pnl:float=0.;unrealized_pnl:float=0.;commission:float=0.;slippage:float=0.;created_at:datetime=field(default_factory=lambda:datetime.now(timezone.utc));updated_at:datetime=field(default_factory=lambda:datetime.now(timezone.utc));peak_equity:float=1000.;max_drawdown:float=0.
    def __post_init__(self):
        if self.initial_balance<=0:raise ValueError("paper initial balance must be positive")
        if self.balance==1000. and self.initial_balance!=1000.:self.balance=self.equity=self.free_margin=self.peak_equity=self.initial_balance
    def mark(self,unrealized:float,timestamp:datetime):
        self.unrealized_pnl=unrealized;self.equity=self.balance+unrealized;self.free_margin=self.equity-self.used_margin;self.peak_equity=max(self.peak_equity,self.equity);drawdown=(self.peak_equity-self.equity)/self.peak_equity if self.peak_equity else 0.;self.max_drawdown=max(self.max_drawdown,drawdown);self.updated_at=timestamp
    def realize(self,gross:float,commission:float,slippage_cost:float,timestamp:datetime):
        net=gross-commission-slippage_cost;self.realized_pnl+=net;self.commission+=commission;self.slippage+=slippage_cost;self.balance+=net;self.mark(0.,timestamp);return net

@dataclass(slots=True)
class PaperPosition:
    position_id:str;symbol:str;direction:Direction;entry_price:float;average_entry_price:float;quantity:float;notional:float;unrealized_pnl:float;realized_pnl:float;opened_at:datetime;updated_at:datetime;state:PositionState=PositionState.OPEN;dca_entries:int=0;stop_loss:float|None=None;take_profit:float|None=None
    @classmethod
    def open(cls,symbol,direction,price,quantity,timestamp,stop_loss=None,take_profit=None):return cls(uuid4().hex,symbol,direction,price,price,quantity,price*quantity,0.,0.,timestamp,timestamp,stop_loss=stop_loss,take_profit=take_profit)
    def mark(self,price,timestamp):self.unrealized_pnl=(price-self.average_entry_price)*self.quantity*(1 if self.direction is Direction.LONG else -1);self.updated_at=timestamp;return self.unrealized_pnl
    def add(self,price,quantity,timestamp):self.average_entry_price=(self.average_entry_price*self.quantity+price*quantity)/(self.quantity+quantity);self.quantity+=quantity;self.notional=self.average_entry_price*self.quantity;self.dca_entries+=1;self.updated_at=timestamp

@dataclass(frozen=True,slots=True)
class PaperOrderRequest:
    symbol:str;direction:Direction;order_type:OrderType;quantity:float;timestamp:datetime;requested_price:float|None=None;position_id:str|None=None;strategy_version:str="phase6.strategy.v1";model_version:str|None=None;stop_loss:float|None=None;take_profit:float|None=None;source_timestamp:datetime|None=None
@dataclass(frozen=True,slots=True)
class PaperOrder:
    order_id:str;position_id:str|None;symbol:str;direction:Direction;order_type:OrderType;requested_price:float|None;executed_price:float;quantity:float;slippage:float;commission:float;timestamp:datetime;strategy_version:str;model_version:str|None;spread:float;spread_source:str
@dataclass(frozen=True,slots=True)
class PaperExecutionResult:
    accepted:bool;order:PaperOrder|None;rejection_reason:str|None;latency_ms:float;gross_pnl:float=0.;net_pnl:float=0.;reason_codes:tuple[str,...]=()
@dataclass(frozen=True,slots=True)
class DCAEvent:
    dca_id:str;position_id:str;entry_number:int;timestamp:datetime;price:float;quantity:float;reason:str;market_regime:str;structure_state:str;risk_state:str
@dataclass(frozen=True,slots=True)
class TradeJournal:
    trade_id:str;timestamp:datetime;entry_reason:tuple[str,...];market_context:dict[str,Any];mtf_context:dict[str,Any];liquidity_context:dict[str,Any];indicator_context:dict[str,Any];nn_prediction:dict[str,Any]|None;risk_decision:dict[str,Any];dca_history:tuple[dict[str,Any],...];exit_reason:tuple[str,...]|None;final_result:dict[str,Any]|None
