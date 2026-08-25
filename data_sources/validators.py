from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Sequence

from data_quality.validator import timeframe_delta

class QualityStatus(StrEnum): VALID="VALID"; WARNING="WARNING"; INVALID="INVALID"

@dataclass(frozen=True, slots=True)
class DataQualityReport:
    timestamp: datetime
    symbol: str
    timeframe: str
    completeness: float
    freshness: float
    timestamp_integrity: float
    ohlc_integrity: float
    duplicate_rate: float
    gap_rate: float
    status: QualityStatus
    reasons: tuple[str, ...]
    source: str

class MarketQualityValidator:
    def evaluate(self, candles: Sequence[Any], *, symbol: str, timeframe: str, as_of: datetime | None=None, source="unknown") -> DataQualityReport:
        now = as_of or datetime.now(timezone.utc); rows=sorted(candles,key=lambda r:r["timestamp"] if isinstance(r,dict) else r.timestamp)
        if not rows: return DataQualityReport(now,symbol,timeframe,0,0,0,0,0,1,QualityStatus.INVALID,("NO_DATA",),source)
        val=lambda r,n:r[n] if isinstance(r,dict) else getattr(r,n)
        stamps=[val(r,"timestamp") for r in rows];stamps=[s if s.tzinfo else s.replace(tzinfo=timezone.utc) for s in stamps]; unique=len(set(stamps)); duplicate=1-unique/len(rows)
        integrity=sum(float(val(r,"low"))<=min(float(val(r,"open")),float(val(r,"close")))<=max(float(val(r,"open")),float(val(r,"close")))<=float(val(r,"high")) for r in rows)/len(rows)
        ordered=1.0 if len(stamps)<=1 else sum(stamps[i]>stamps[i-1] for i in range(1,len(stamps)))/(len(stamps)-1)
        delta=timeframe_delta(timeframe); gaps=sum(stamps[i]-stamps[i-1]>delta for i in range(1,len(stamps))); gap_rate=gaps/max(1,len(stamps)-1)
        expected=max(1,int((stamps[-1]-stamps[0])/delta)+1); completeness=min(1,unique/expected)
        latest=stamps[-1] if stamps[-1].tzinfo else stamps[-1].replace(tzinfo=timezone.utc); freshness=max(0,1-(now-latest).total_seconds()/max(delta.total_seconds()*3,1))
        reasons=[]
        if integrity<1: reasons.append("INVALID_OHLC")
        if duplicate>0: reasons.append("DUPLICATES")
        if gap_rate>.1: reasons.append("EXCESSIVE_GAPS")
        if freshness==0: reasons.append("STALE_DATA")
        status=QualityStatus.INVALID if integrity<1 or ordered<1 else QualityStatus.WARNING if reasons else QualityStatus.VALID
        return DataQualityReport(now,symbol,timeframe,round(completeness,4),round(freshness,4),round(ordered,4),round(integrity,4),round(duplicate,4),round(gap_rate,4),status,tuple(reasons),source)
