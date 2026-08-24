from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from enum import StrEnum
from typing import Any, Sequence

from data_quality.validator import MarketDataValidator, timeframe_delta


class GapSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class MarketDataGap:
    symbol: str
    timeframe: str
    start_timestamp: datetime
    end_timestamp: datetime
    expected_candles: int
    actual_candles: int
    severity: GapSeverity
    reason: str


class FreshnessStatus(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    MISSING = "MISSING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class DataFreshness:
    symbol: str
    timeframe: str
    last_candle_timestamp: datetime | None
    ingestion_timestamp: datetime
    data_age_seconds: float | None
    status: FreshnessStatus


@dataclass(frozen=True, slots=True)
class TimeframeReadiness:
    timeframe: str
    status: str
    count: int
    freshness: FreshnessStatus
    gaps: int
    duplicate_candles: int
    invalid_candles: int


@dataclass(frozen=True, slots=True)
class MarketDataReadinessReport:
    generated_at: datetime
    symbols: dict[str, dict[str, TimeframeReadiness]]


def is_fx_market_open(timestamp: datetime) -> bool:
    timestamp = timestamp.astimezone(timezone.utc)
    weekday = timestamp.weekday()
    if weekday < 4:
        return True
    if weekday == 4:
        return timestamp.hour < 22
    if weekday == 5:
        return False
    return timestamp.hour >= 22


def detect_market_data_gaps(candles: Sequence[Any]) -> list[MarketDataGap]:
    if len(candles) < 2:
        return []
    value = lambda row, name: row[name] if isinstance(row, dict) else getattr(row, name)
    ordered = sorted(candles, key=lambda row: value(row, "timestamp"))
    result: list[MarketDataGap] = []
    for previous, current in zip(ordered, ordered[1:]):
        if value(previous, "symbol") != value(current, "symbol") or value(previous, "timeframe") != value(current, "timeframe"):
            continue
        timeframe = str(value(previous, "timeframe"))
        delta = timeframe_delta(timeframe)
        start = value(previous, "timestamp") + delta
        end = value(current, "timestamp")
        if start >= end:
            continue
        expected = _count_open_intervals(start, end, delta)
        if not expected:
            severity, reason, expected = GapSeverity.INFO, "FX_WEEKEND_OR_MARKET_CLOSED", 0
        else:
            severity = GapSeverity.CRITICAL if expected >= 12 else GapSeverity.WARNING
            reason = "MISSING_MARKET_CANDLES"
        result.append(MarketDataGap(
            str(value(previous, "symbol")), timeframe, start, end,
            expected, 0, severity, reason,
        ))
    return result


def _count_open_intervals(start: datetime, end: datetime, delta: timedelta) -> int:
    """Count aligned expected points in O(number of UTC days), not O(candles)."""
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    total = 0
    day = datetime.combine(start.date(), time.min, tzinfo=timezone.utc)
    while day < end:
        weekday = day.weekday()
        if weekday < 4:
            open_start, open_end = day, day + timedelta(days=1)
        elif weekday == 4:
            open_start, open_end = day, day + timedelta(hours=22)
        elif weekday == 6:
            open_start, open_end = day + timedelta(hours=22), day + timedelta(days=1)
        else:
            day += timedelta(days=1)
            continue
        lower, upper = max(start, open_start), min(end, open_end)
        if lower < upper:
            elapsed = lower - start
            quotient, remainder = divmod(elapsed, delta)
            first = start + delta * (quotient + (1 if remainder else 0))
            if first < upper:
                total += ((upper - first - timedelta(microseconds=1)) // delta) + 1
        day += timedelta(days=1)
    return int(total)


def calculate_freshness(
    symbol: str, timeframe: str, last_candle: Any | None,
    *, threshold_seconds: float, now: datetime | None = None,
) -> DataFreshness:
    now = now or datetime.now(timezone.utc)
    if last_candle is None:
        return DataFreshness(symbol, timeframe, None, now, None, FreshnessStatus.MISSING)
    try:
        timestamp = last_candle["timestamp"] if isinstance(last_candle, dict) else last_candle.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - timestamp.astimezone(timezone.utc)).total_seconds())
        status = FreshnessStatus.FRESH if age <= threshold_seconds else FreshnessStatus.STALE
        return DataFreshness(symbol, timeframe, timestamp, now, round(age, 3), status)
    except Exception:
        return DataFreshness(symbol, timeframe, None, now, None, FreshnessStatus.ERROR)


def validate_candle_batch(candles: Sequence[dict[str, Any]]) -> None:
    validator = MarketDataValidator()
    previous: datetime | None = None
    keys: set[tuple[str, str, datetime, str]] = set()
    for candle in candles:
        validator.validate_candle(candle)
        timestamp = candle["timestamp"]
        if previous is not None and timestamp < previous:
            raise ValueError("candle batch timestamps must be ordered")
        previous = timestamp
        key = (candle["symbol"], candle["timeframe"], timestamp, candle["source"])
        if key in keys:
            raise ValueError("candle batch contains duplicate timestamps for the same source")
        keys.add(key)
