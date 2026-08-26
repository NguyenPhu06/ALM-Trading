from __future__ import annotations
from dataclasses import dataclass
from time import monotonic
from uuid import uuid4
from paper.models import Direction,OrderType,PaperExecutionResult,PaperOrder,PaperOrderRequest,TradingEnvironment

@dataclass(frozen=True,slots=True)
class ExecutionConfig:
    fallback_spread:float=.0001;fixed_slippage:float=.00002;percentage_slippage:float=0.;volatility_slippage_multiplier:float=.05;commission_per_trade:float=0.;commission_percentage:float=0.;latency_ms:float=25.
class LiveExecutionBlocked(RuntimeError):pass
class EnvironmentSafetyLock:
    def __init__(self,*,live_trading_enabled:bool=False):self.live_trading_enabled=live_trading_enabled
    def assert_allowed(self,environment:TradingEnvironment):
        if environment is TradingEnvironment.LIVE or self.live_trading_enabled:raise LiveExecutionBlocked("LIVE_EXECUTION_BLOCKED")

class PaperExecutionEngine:
    def __init__(self,config:ExecutionConfig|None=None,safety:EnvironmentSafetyLock|None=None):self.config=config or ExecutionConfig();self.safety=safety or EnvironmentSafetyLock()
    def execute(self,request:PaperOrderRequest,*,quote:dict|None,volatility:float=0.,environment:TradingEnvironment=TradingEnvironment.PAPER)->PaperExecutionResult:
        started=monotonic();self.safety.assert_allowed(environment)
        if request.source_timestamp and request.source_timestamp>request.timestamp:return PaperExecutionResult(False,None,"FUTURE_DATA_REJECTED",0.,reason_codes=("WHY_REJECTED:FUTURE_DATA",))
        if request.quantity<=0:return PaperExecutionResult(False,None,"INVALID_QUANTITY",0.,reason_codes=("WHY_REJECTED:INVALID_QUANTITY",))
        reference=request.requested_price
        bid=quote.get("bid") if quote else None;ask=quote.get("ask") if quote else None
        spread_source="PROVIDER_BID_ASK" if bid is not None and ask is not None else "CONFIGURED_FALLBACK_MODEL"
        if reference is None:
            if bid is not None and ask is not None:reference=float(ask if request.direction is Direction.LONG else bid)
            elif quote and quote.get("mid_price") is not None:reference=float(quote["mid_price"])+(self.config.fallback_spread/2)*(1 if request.direction is Direction.LONG else -1)
            else:return PaperExecutionResult(False,None,"QUOTE_UNAVAILABLE",0.,reason_codes=("WHY_REJECTED:QUOTE_UNAVAILABLE",))
        spread=float(ask-bid) if bid is not None and ask is not None else self.config.fallback_spread
        slip=self.config.fixed_slippage+abs(reference)*self.config.percentage_slippage+abs(volatility)*self.config.volatility_slippage_multiplier
        is_exit=request.order_type in {OrderType.CLOSE,OrderType.REDUCE};sign=1 if request.direction is Direction.LONG else -1
        executed=reference+sign*slip*(-1 if is_exit else 1)
        commission=self.config.commission_per_trade+abs(executed*request.quantity)*self.config.commission_percentage
        order=PaperOrder(uuid4().hex,request.position_id,request.symbol,request.direction,request.order_type,request.requested_price,executed,request.quantity,slip,commission,request.timestamp,request.strategy_version,request.model_version,spread,spread_source)
        return PaperExecutionResult(True,order,None,max(self.config.latency_ms,(monotonic()-started)*1000),reason_codes=("WHY_ENTRY:PAPER_EXECUTION" if not is_exit else "WHY_EXIT:PAPER_EXECUTION",))

class PositionSizingEngine:
    def __init__(self,*,max_position_size:float=10.,max_notional:float=100000.,max_account_risk:float=.02):self.max_position_size=max_position_size;self.max_notional=max_notional;self.max_account_risk=max_account_risk
    def calculate(self,method:str,*,balance:float,price:float,fixed_size:float=1.,risk_percentage:float=.01,stop_distance:float|None=None,atr:float|None=None)->float:
        if method=="fixed_size":size=fixed_size
        elif method=="risk_percentage":size=balance*risk_percentage/max(stop_distance or 0.,1e-12)
        elif method=="volatility_based":size=balance*risk_percentage/max(atr or 0.,1e-12)
        else:raise ValueError("unknown position sizing method")
        cap=min(self.max_position_size,self.max_notional/price,(balance*self.max_account_risk)/max(stop_distance or price*.01,1e-12));return max(0.,min(size,cap))
