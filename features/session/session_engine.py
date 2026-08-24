from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from enum import StrEnum
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from features.candles import candle_close_time


class SessionName(StrEnum):
    ASIA = "ASIA"
    LONDON = "LONDON"
    NEW_YORK = "NEW_YORK"
    LONDON_NEW_YORK_OVERLAP = "LONDON_NEW_YORK_OVERLAP"
    OVERLAP = "LONDON_NEW_YORK_OVERLAP"
    OFF_SESSION = "OFF_SESSION"


@dataclass(frozen=True, slots=True)
class TimeFeatures:
    session: SessionName
    hour: int
    minute: int
    day_of_week: int
    is_even_hour: bool


@dataclass(frozen=True, slots=True)
class SessionLevel:
    event_timestamp: datetime
    session: SessionName
    high: float
    low: float
    is_current: bool


class SessionEngine:
    """Assign sessions and derive causal running/previous-session levels."""

    def __init__(
        self,
        *,
        timezone: str = "UTC",
        asia: tuple[str, str] = ("00:00", "09:00"),
        london: tuple[str, str] = ("07:00", "16:00"),
        new_york: tuple[str, str] = ("13:00", "22:00"),
    ):
        self.timezone = ZoneInfo(timezone)
        self.windows = {
            SessionName.ASIA: tuple(self._parse_time(value) for value in asia),
            SessionName.LONDON: tuple(self._parse_time(value) for value in london),
            SessionName.NEW_YORK: tuple(self._parse_time(value) for value in new_york),
        }

    @staticmethod
    def _parse_time(value: str) -> time:
        return time.fromisoformat(value)

    @staticmethod
    def _inside(value: time, window: tuple[time, time]) -> bool:
        start, end = window
        return start <= value < end if start < end else value >= start or value < end

    @staticmethod
    def _aware(timestamp: datetime) -> datetime:
        # SQLite drops timezone metadata on round-trip; database timestamps are
        # contractually UTC and ingestion rejects naive input.
        return timestamp if timestamp.tzinfo is not None and timestamp.utcoffset() is not None else timestamp.replace(tzinfo=timezone.utc)

    def session_for(self, timestamp: datetime) -> SessionName:
        timestamp = self._aware(timestamp)
        local_time = timestamp.astimezone(self.timezone).time().replace(tzinfo=None)
        london = self._inside(local_time, self.windows[SessionName.LONDON])
        new_york = self._inside(local_time, self.windows[SessionName.NEW_YORK])
        if london and new_york:
            return SessionName.LONDON_NEW_YORK_OVERLAP
        if london:
            return SessionName.LONDON
        if new_york:
            return SessionName.NEW_YORK
        if self._inside(local_time, self.windows[SessionName.ASIA]):
            return SessionName.ASIA
        return SessionName.OFF_SESSION

    def time_features(self, timestamp: datetime) -> TimeFeatures:
        timestamp = self._aware(timestamp)
        local = timestamp.astimezone(self.timezone)
        return TimeFeatures(
            session=self.session_for(timestamp),
            hour=local.hour,
            minute=local.minute,
            day_of_week=local.weekday(),
            is_even_hour=local.minute == 0 and local.hour % 2 == 0,
        )

    def levels(self, candles: Sequence[Any]) -> list[SessionLevel]:
        levels: list[SessionLevel] = []
        current_key: tuple[Any, SessionName] | None = None
        running_high = running_low = 0.0
        previous: tuple[SessionName, float, float] | None = None

        for candle in candles:
            timestamp = candle["timestamp"] if isinstance(candle, dict) else candle.timestamp
            aware_timestamp = self._aware(timestamp)
            session = self.session_for(timestamp)
            if session is SessionName.OFF_SESSION:
                continue
            local_date = aware_timestamp.astimezone(self.timezone).date()
            key = (local_date, session)
            high = float(candle["high"] if isinstance(candle, dict) else candle.high)
            low = float(candle["low"] if isinstance(candle, dict) else candle.low)
            if key != current_key:
                if current_key is not None:
                    previous = (current_key[1], running_high, running_low)
                current_key = key
                running_high, running_low = high, low
            else:
                running_high = max(running_high, high)
                running_low = min(running_low, low)
            if previous:
                levels.append(SessionLevel(candle_close_time(candle), previous[0], previous[1], previous[2], False))
            levels.append(SessionLevel(candle_close_time(candle), session, running_high, running_low, True))
        return levels
