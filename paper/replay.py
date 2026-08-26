from __future__ import annotations
from dataclasses import dataclass
from typing import Callable,Sequence,Any
@dataclass(frozen=True,slots=True)
class ReplayStep:timestamp:object;action:str;details:dict
class PaperMarketReplay:
    def run(self,candles:Sequence[dict],handler:Callable[[dict,tuple[dict,...]],str])->list[ReplayStep]:
        ordered=sorted(candles,key=lambda c:c["timestamp"]);history=[];steps=[]
        for candle in ordered:
            if not candle.get("is_closed",True):continue
            action=handler(candle,tuple(history));steps.append(ReplayStep(candle["timestamp"],action,{"price":candle["close"]}));history.append(candle)
        return steps

