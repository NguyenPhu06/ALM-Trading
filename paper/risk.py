from __future__ import annotations
from dataclasses import dataclass
from datetime import date,datetime

@dataclass(frozen=True,slots=True)
class PaperRiskDecision:
    allowed:bool;rejection_reasons:tuple[str,...];risk_state:str
class GlobalKillSwitch:
    """Refuses every exposure-increasing action; exposure-reducing management stays available.

    New entries and DCA both increase exposure, so both are refused while the switch is on.
    REDUCE and CLOSE are how an operator gets flat, so they are never blocked.
    """
    def __init__(self):self.enabled=False
    def activate(self):self.enabled=True
    def deactivate(self):self.enabled=False
    def permits(self,*,new_entry:bool,increases_exposure:bool=False):
        return not (self.enabled and (new_entry or increases_exposure))

class DailyRiskManager:
    def __init__(self,daily_loss_limit:float=.03):self.daily_loss_limit=daily_loss_limit;self.day:date|None=None;self.daily_start_equity=0.;self.daily_pnl=0.;self.daily_drawdown=0.;self.paused=False
    def update(self,timestamp:datetime,equity:float):
        if self.day!=timestamp.date():self.day=timestamp.date();self.daily_start_equity=equity;self.daily_pnl=0.;self.daily_drawdown=0.;self.paused=False
        self.daily_pnl=equity-self.daily_start_equity;self.daily_drawdown=max(0.,-self.daily_pnl/self.daily_start_equity) if self.daily_start_equity else 0.;self.paused=self.daily_drawdown>=self.daily_loss_limit;return self.paused

class PaperRiskEngine:
    def __init__(self,*,max_drawdown=.2,max_exposure=100000.,max_position_size=10.,max_dca_entries=3,max_daily_loss=.03,max_concurrent_positions=3,max_spread=.005,kill_switch=None):self.max_drawdown=max_drawdown;self.max_exposure=max_exposure;self.max_position_size=max_position_size;self.max_dca_entries=max_dca_entries;self.max_daily_loss=max_daily_loss;self.max_concurrent_positions=max_concurrent_positions;self.max_spread=max_spread;self.kill_switch=kill_switch or GlobalKillSwitch()
    def evaluate(self,*,new_entry=True,increases_exposure=False,drawdown=0.,exposure=0.,quantity=0.,dca_entries=0,daily_drawdown=0.,concurrent_positions=0,volatility="NORMAL_VOLATILITY",spread=0.,news_risk="LOW",data_quality="VALID",provider_status="ONLINE",model_valid=True,strategy_valid=True)->PaperRiskDecision:
        r=[]
        if not self.kill_switch.permits(new_entry=new_entry,increases_exposure=increases_exposure):r.append("GLOBAL_KILL_SWITCH")
        if drawdown>=self.max_drawdown:r.append("MAXIMUM_DRAWDOWN")
        if exposure>=self.max_exposure:r.append("MAXIMUM_EXPOSURE")
        if quantity>self.max_position_size:r.append("MAXIMUM_POSITION_SIZE")
        if dca_entries>=self.max_dca_entries:r.append("MAXIMUM_DCA_ENTRIES")
        if daily_drawdown>=self.max_daily_loss:r.append("MAXIMUM_DAILY_LOSS")
        if concurrent_positions>=self.max_concurrent_positions and new_entry:r.append("MAXIMUM_CONCURRENT_POSITIONS")
        if volatility=="EXTREME_VOLATILITY":r.append("EXTREME_VOLATILITY")
        if spread>self.max_spread:r.append("SPREAD_TOO_WIDE")
        if news_risk in {"HIGH","EXTREME"}:r.append("HIGH_IMPACT_EVENT_NEARBY")
        if data_quality!="VALID":r.append("DATA_QUALITY_INVALID")
        if provider_status!="ONLINE":r.append("PROVIDER_UNAVAILABLE")
        if not model_valid:r.append("MODEL_FAILURE")
        if not strategy_valid:r.append("STRATEGY_INVALID")
        return PaperRiskDecision(not r,tuple(r),"ALLOWED" if not r else "ORDER_REJECTED")

def validate_model_prediction(prediction)->bool:
    if prediction is None:return False
    try:
        values=[float(prediction[k]) for k in ("prob_up","prob_down","prob_neutral")]
        return all(v==v and 0<=v<=1 for v in values) and abs(sum(values)-1)<1e-6
    except (KeyError,TypeError,ValueError):return False
