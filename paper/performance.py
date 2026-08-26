from __future__ import annotations
from dataclasses import dataclass
from statistics import mean
@dataclass(frozen=True,slots=True)
class PaperPerformance:
    total_trades:int;winning_trades:int;losing_trades:int;win_rate:float;gross_profit:float;gross_loss:float;net_profit:float;profit_factor:float|None;expectancy:float;average_win:float;average_loss:float;max_drawdown:float;average_holding_time:float;dca_frequency:float;average_dca_depth:float;commission:float;slippage:float
def calculate_performance(trades):
    rows=list(trades);nets=[float(r.get("net_pnl",0)) for r in rows];wins=[n for n in nets if n>0];losses=[n for n in nets if n<0];gp=sum(float(r.get("gross_pnl",0)) for r in rows if float(r.get("gross_pnl",0))>0);gl=abs(sum(float(r.get("gross_pnl",0)) for r in rows if float(r.get("gross_pnl",0))<0));total=len(rows);depth=[int(r.get("dca_depth",0)) for r in rows]
    return PaperPerformance(total,len(wins),len(losses),len(wins)/total if total else 0.,gp,gl,sum(nets),gp/gl if gl else(None if not gp else float("inf")),mean(nets) if nets else 0.,mean(wins) if wins else 0.,mean(losses) if losses else 0.,max((float(r.get("drawdown",0)) for r in rows),default=0.),mean([float(r.get("holding_minutes",0)) for r in rows]) if rows else 0.,sum(d>0 for d in depth)/total if total else 0.,mean(depth) if depth else 0.,sum(float(r.get("commission",0)) for r in rows),sum(float(r.get("slippage",0)) for r in rows))
def grouped_performance(trades,field):
    groups={}
    for trade in trades:groups.setdefault(str(trade.get(field,"UNKNOWN")),[]).append(trade)
    return {key:calculate_performance(rows) for key,rows in groups.items()}
