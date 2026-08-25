from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

class PaperOrderStatus(StrEnum): OPEN="OPEN"; CLOSED="CLOSED"; CANCELLED="CANCELLED"
@dataclass(frozen=True,slots=True)
class PaperOrder:
    order_id:str; symbol:str; direction:str; entry:float; size:float; stop:float|None; take_profit:float|None; timestamp:datetime; strategy_version:str; model_version:str|None; status:PaperOrderStatus=PaperOrderStatus.OPEN

class PaperExecutionProvider:
    """In-memory simulation only. No broker transport exists."""
    def __init__(self):self._orders={}
    def submit_order(self,*,symbol,direction,entry,size,stop,take_profit,timestamp,strategy_version,model_version=None):
        if size<=0:raise ValueError("paper order size must be positive")
        order=PaperOrder(uuid4().hex,symbol,direction,entry,size,stop,take_profit,timestamp,strategy_version,model_version);self._orders[order.order_id]=order;return order
    def modify_order(self,order_id,*,stop=None,take_profit=None):
        order=self._orders[order_id];updated=replace(order,stop=stop if stop is not None else order.stop,take_profit=take_profit if take_profit is not None else order.take_profit);self._orders[order_id]=updated;return updated
    def close_order(self,order_id):
        order=replace(self._orders[order_id],status=PaperOrderStatus.CLOSED);self._orders[order_id]=order;return order
    def get_positions(self):return tuple(order for order in self._orders.values() if order.status is PaperOrderStatus.OPEN)
