from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

@dataclass(frozen=True, slots=True)
class COTPosition:
    report_date: date
    asset: str
    commercial_long: int
    commercial_short: int
    noncommercial_long: int
    noncommercial_short: int
    open_interest: int
    net_position: int
    net_change: int | None
    position_percentile: float | None
    source: str = "CFTC_TFF"
    latency_notice: str = "COT is weekly delayed public positioning data, not realtime"

class COTProvider:
    def calculate(self, reports: Sequence[dict], asset: str) -> COTPosition | None:
        rows=sorted((r for r in reports if str(r.get("asset",r.get("market",""))).upper()==asset.upper()),key=lambda r:r["report_date"])
        if not rows:return None
        row=rows[-1]; commercial_long=int(row.get("commercial_long",row.get("dealer_long",0))); commercial_short=int(row.get("commercial_short",row.get("dealer_short",0)))
        non_long=int(row.get("noncommercial_long",row.get("leveraged_money_long",0))); non_short=int(row.get("noncommercial_short",row.get("leveraged_money_short",0)))
        net=non_long-non_short; historical=[int(r.get("noncommercial_long",r.get("leveraged_money_long",0)))-int(r.get("noncommercial_short",r.get("leveraged_money_short",0))) for r in rows]
        change=net-historical[-2] if len(historical)>1 else None
        percentile=sum(value<=net for value in historical)/len(historical)*100 if historical else None
        return COTPosition(row["report_date"],asset,commercial_long,commercial_short,non_long,non_short,int(row.get("open_interest",0)),net,change,round(percentile,2) if percentile is not None else None)

