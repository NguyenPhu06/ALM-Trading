from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence

from data_quality.validator import timeframe_delta


def candle_value(candle: Any, name: str, default: Any = None) -> Any:
    if isinstance(candle, dict):
        return candle.get(name, default)
    return getattr(candle, name, default)


def candle_is_closed(candle: Any) -> bool:
    return candle_value(candle, "is_closed", True) is True


def utc_aware(timestamp: datetime) -> datetime:
    aware = timestamp if timestamp.tzinfo is not None and timestamp.utcoffset() is not None else timestamp.replace(tzinfo=timezone.utc)
    return aware.astimezone(timezone.utc)


def candle_close_time(candle: Any) -> datetime:
    explicit = candle_value(candle, "close_time")
    if explicit is not None:
        return utc_aware(explicit)
    return utc_aware(candle_value(candle, "timestamp") + timeframe_delta(str(candle_value(candle, "timeframe"))))


def closed_candle_prefix(candles: Sequence[Any], *, as_of_index: int | None = None) -> list[Any]:
    end = len(candles) - 1 if as_of_index is None else min(as_of_index, len(candles) - 1)
    result: list[Any] = []
    for candle in candles[: end + 1]:
        if not candle_is_closed(candle):
            break
        result.append(candle)
    return result
