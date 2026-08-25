from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from features.session import SessionEngine, SessionName


@dataclass(frozen=True, slots=True)
class TradingSessionContext:
    session: SessionName
    session_start: datetime | None
    session_end: datetime | None
    minutes_from_session_open: int | None
    minutes_to_session_close: int | None
    is_even_hour_entry: bool


class TradingSessionEngine(SessionEngine):
    def context(self, timestamp: datetime) -> TradingSessionContext:
        aware = self._aware(timestamp)
        local = aware.astimezone(self.timezone)
        session = self.session_for(aware)
        if session is SessionName.OFF_SESSION:
            return TradingSessionContext(session, None, None, None, None, self.time_features(aware).is_even_hour)
        base = SessionName.LONDON if session is SessionName.LONDON_NEW_YORK_OVERLAP else session
        start_time, end_time = self.windows[base]
        start = local.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
        end = local.replace(hour=end_time.hour, minute=end_time.minute, second=0, microsecond=0)
        if end <= start:
            end += timedelta(days=1)
        if local < start:
            start -= timedelta(days=1)
            end -= timedelta(days=1)
        return TradingSessionContext(
            session, start.astimezone(timezone.utc), end.astimezone(timezone.utc),
            max(0, int((local - start).total_seconds() // 60)),
            max(0, int((end - local).total_seconds() // 60)), self.time_features(aware).is_even_hour,
        )
