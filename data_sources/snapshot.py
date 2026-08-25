from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from data_sources.providers.base import BaseMarketDataProvider
from data_sources.providers.context import Availability, EconomicCalendarProvider, InstitutionalObservation, InstitutionalPositionProvider, NewsRiskEngine
from data_sources.validators import DataQualityReport, MarketQualityValidator, QualityStatus
from features.session import SessionEngine

TIMEFRAMES=("D1","H4","H1","M30","M15","M5")

@dataclass(frozen=True, slots=True)
class RealMarketSnapshot:
    timestamp: datetime
    symbol: str
    quote: dict[str,Any] | None
    mtf_candles: dict[str,tuple[dict[str,Any],...]]
    market_session: str
    volatility: dict[str,Any]
    data_quality: dict[str,DataQualityReport]
    cot_context: dict[str,Any] | None
    institutional_proxy: dict[str,Any]
    provider_status: dict[str,Any]
    news_risk: str
    strategy_allowed: bool
    reasons: tuple[str,...]

class RealMarketSnapshotEngine:
    def __init__(self, provider:BaseMarketDataProvider, *, quality=None, sessions=None, calendar=None, institutional=None):
        self.provider=provider; self.quality=quality or MarketQualityValidator(); self.sessions=sessions or SessionEngine(); self.calendar=calendar or EconomicCalendarProvider(); self.institutional=institutional or InstitutionalPositionProvider()
    def build(self,symbol:str,*,as_of:datetime|None=None,limit:int=200,cot_context=None)->RealMarketSnapshot:
        now=as_of or datetime.now(timezone.utc); candles={}; reports={}; reasons=[]
        for tf in TIMEFRAMES:
            rows=[]
            for raw in self.provider.get_candles(symbol,tf,limit=limit):
                timestamp=raw["timestamp"] if raw["timestamp"].tzinfo else raw["timestamp"].replace(tzinfo=timezone.utc)
                if raw.get("is_closed",True) and timestamp<=now: rows.append({**raw,"timestamp":timestamp})
            candles[tf]=tuple(rows); reports[tf]=self.quality.evaluate(rows,symbol=symbol,timeframe=tf,as_of=now,source=self.provider.name)
            if reports[tf].status is QualityStatus.INVALID: reasons.append(f"DATA_QUALITY_INVALID:{tf}")
        status=self.provider.health_check(); inst=self.institutional.get_observation(symbol)
        if inst.provider_status is Availability.AVAILABLE and inst.timestamp>now:
            inst=InstitutionalObservation(now,symbol,Availability.UNAVAILABLE,None,0.,None,True);reasons.append("FUTURE_INSTITUTIONAL_CONTEXT_REJECTED")
        currencies=(symbol[:3],symbol[3:6]) if len(symbol)>=6 else (symbol,)
        events=self.calendar.get_events(now,now); news=NewsRiskEngine().evaluate(events,timestamp=now,currencies=currencies)
        if status.status.value not in {"HEALTHY","ONLINE"}:reasons.append("PROVIDER_UNAVAILABLE")
        if news.value in {"HIGH","EXTREME"}:reasons.append("HIGH_IMPACT_EVENT_NEARBY")
        if cot_context and isinstance(cot_context,dict) and isinstance(cot_context.get("timestamp"),datetime) and cot_context["timestamp"]>now:
            cot_context=None;reasons.append("FUTURE_COT_CONTEXT_REJECTED")
        quote=self.provider.get_latest_quote(symbol)
        if quote and isinstance(quote.get("timestamp"),datetime):
            quote_time=quote["timestamp"] if quote["timestamp"].tzinfo else quote["timestamp"].replace(tzinfo=timezone.utc)
            if quote_time>now:quote=None;reasons.append("FUTURE_QUOTE_REJECTED")
        m5=candles["M5"]; volatility={"last_range":float(m5[-1]["high"])-float(m5[-1]["low"])} if m5 else {}
        return RealMarketSnapshot(now,symbol,quote,candles,self.sessions.session_for(now).value,volatility,reports,cot_context,asdict(inst),asdict(status),news.value,not reasons,tuple(reasons))
