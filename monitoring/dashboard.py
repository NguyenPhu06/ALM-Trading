from __future__ import annotations
from dataclasses import asdict
from datetime import datetime,timezone
from typing import Any
VERSION="phase9.dashboard.v1";TIMEFRAMES=("D1","H4","H1","M30","M15","M5")
DEFAULT_MAX_AGE_SECONDS=300.
STALE_QUALITY={"STALE","INVALID","UNAVAILABLE"}


def _aware(value):
    """Naive timestamps from the database are stored in UTC; treat them as such."""
    if value is None:return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def envelope(data:Any,*,source="backend",quality="UNAVAILABLE",timestamp=None,now=None,
             max_age_seconds=DEFAULT_MAX_AGE_SECONDS):
    """Wrap a payload with observation metadata and a real freshness measurement.

    `timestamp` is the SOURCE timestamp — the candle, snapshot or record the payload
    was built from — not the moment of the response. Age is measured from it.

    A payload carrying no source timestamp has unknown age and is reported stale:
    unknown freshness is never presented to the dashboard as fresh. `now` is
    injectable so freshness is deterministic under test.
    """
    observed=_aware(now) or datetime.now(timezone.utc)
    last_update=_aware(timestamp)
    age=None if last_update is None else max(0.,(observed-last_update).total_seconds())
    stale=(quality in STALE_QUALITY or age is None
           or (max_age_seconds is not None and age>float(max_age_seconds)))
    return {"timestamp":observed,"source":source,"version":VERSION,"data_quality":quality,
            "data":data,"last_update":last_update,"data_age_seconds":age,"stale":stale,
            "max_age_seconds":max_age_seconds}
def alignment(timeframes):
    values=[str(timeframes.get(tf,{}).get("trend","UNKNOWN")) for tf in TIMEFRAMES];known=[v for v in values if v not in {"UNKNOWN","UNAVAILABLE","NEUTRAL"}]
    if not known:return {"score":0,"status":"WAIT","conflict":False}
    bull=sum("BULL" in v for v in known);bear=sum("BEAR" in v for v in known);score=max(bull,bear)/len(known)*100;conflict=bull>0 and bear>0
    return {"score":round(score,1),"status":"CONFLICT" if conflict else "ALIGNED" if score>=80 else "PARTIALLY_ALIGNED","conflict":conflict}
def unavailable_mtf():return {tf:{"trend":"UNAVAILABLE","structure":None,"bos":None,"choch":None,"swing_high":None,"swing_low":None} for tf in TIMEFRAMES}
