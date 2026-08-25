from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Sequence


class Availability(StrEnum): AVAILABLE="AVAILABLE"; UNAVAILABLE="UNAVAILABLE"

@dataclass(frozen=True, slots=True)
class InstitutionalObservation:
    timestamp: datetime
    asset: str
    provider_status: Availability
    institutional_pressure_proxy: float | None
    confidence: float
    source: str | None
    is_proxy: bool = True

class InstitutionalPositionProvider:
    def get_observation(self, asset: str) -> InstitutionalObservation:
        return InstitutionalObservation(datetime.now(timezone.utc), asset, Availability.UNAVAILABLE, None, 0., None, True)

@dataclass(frozen=True, slots=True)
class EconomicEvent:
    event: str
    currency: str
    importance: str
    scheduled_time: datetime
    actual: float | None = None
    forecast: float | None = None
    previous: float | None = None
    source: str = "unknown"

class EconomicCalendarProvider:
    status = Availability.UNAVAILABLE
    def get_events(self, start: datetime, end: datetime) -> list[EconomicEvent]: return []

class NewsRiskState(StrEnum): LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"; EXTREME="EXTREME"

class NewsRiskEngine:
    def evaluate(self, events: Sequence[EconomicEvent], *, timestamp: datetime, currencies: tuple[str,...], window_minutes: int=60) -> NewsRiskState:
        nearby=[e for e in events if e.currency in currencies and abs((e.scheduled_time-timestamp).total_seconds())<=window_minutes*60]
        if any(e.importance.upper()=="HIGH" for e in nearby): return NewsRiskState.HIGH
        if any(e.importance.upper()=="MEDIUM" for e in nearby): return NewsRiskState.MEDIUM
        return NewsRiskState.LOW

