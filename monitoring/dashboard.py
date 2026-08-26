from __future__ import annotations
from dataclasses import asdict
from datetime import datetime,timezone
from typing import Any
VERSION="phase9.dashboard.v1";TIMEFRAMES=("D1","H4","H1","M30","M15","M5")
def envelope(data:Any,*,source="backend",quality="UNAVAILABLE",timestamp=None):
    stamp=timestamp or datetime.now(timezone.utc);return {"timestamp":stamp,"source":source,"version":VERSION,"data_quality":quality,"data":data,"last_update":stamp,"data_age_seconds":0,"stale":quality in {"STALE","INVALID","UNAVAILABLE"}}
def alignment(timeframes):
    values=[str(timeframes.get(tf,{}).get("trend","UNKNOWN")) for tf in TIMEFRAMES];known=[v for v in values if v not in {"UNKNOWN","UNAVAILABLE","NEUTRAL"}]
    if not known:return {"score":0,"status":"WAIT","conflict":False}
    bull=sum("BULL" in v for v in known);bear=sum("BEAR" in v for v in known);score=max(bull,bear)/len(known)*100;conflict=bull>0 and bear>0
    return {"score":round(score,1),"status":"CONFLICT" if conflict else "ALIGNED" if score>=80 else "PARTIALLY_ALIGNED","conflict":conflict}
def unavailable_mtf():return {tf:{"trend":"UNAVAILABLE","structure":None,"bos":None,"choch":None,"swing_high":None,"swing_low":None} for tf in TIMEFRAMES}
