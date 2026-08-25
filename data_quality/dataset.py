from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from data_quality.market_data import detect_market_data_gaps
from data_quality.validator import DataValidationError, MarketDataValidator


def _value(row: Any, name: str, default: Any = None) -> Any:
    return row.get(name, default) if isinstance(row, dict) else getattr(row, name, default)


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    symbol: str
    timeframe: str
    start_time: datetime | None
    end_time: datetime | None
    total_rows: int
    duplicate_rows: int
    missing_rows: int
    invalid_rows: int
    quality_score: float
    incomplete_rows: int = 0
    timestamp_order_errors: int = 0
    timezone_errors: int = 0
    issues: tuple[str, ...] = field(default_factory=tuple)


class HistoricalDataQualityEngine:
    """Audit historical candles without repairing or silently filling them."""

    def __init__(self) -> None:
        self.validator = MarketDataValidator()

    def inspect(self, candles: Sequence[Any], *, symbol: str, timeframe: str) -> DataQualityReport:
        rows = list(candles)
        timestamps: list[datetime] = []
        seen: set[datetime] = set()
        duplicate_rows = invalid_rows = incomplete_rows = order_errors = timezone_errors = 0
        issues: list[str] = []
        previous: datetime | None = None
        valid_for_gaps: list[Any] = []

        for row in rows:
            timestamp = _value(row, "timestamp")
            if isinstance(timestamp, datetime):
                timestamps.append(timestamp)
                if timestamp in seen:
                    duplicate_rows += 1
                seen.add(timestamp)
                if previous is not None and timestamp <= previous:
                    order_errors += 1
                previous = timestamp
                if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                    timezone_errors += 1
                elif timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
                    timezone_errors += 1
            if _value(row, "is_closed", True) is not True:
                incomplete_rows += 1
            candidate = self._mapping(row)
            try:
                self.validator.validate_candle(candidate)
                if candidate["symbol"] != symbol.upper() or candidate["timeframe"] != timeframe:
                    raise DataValidationError("symbol/timeframe mismatch")
                valid_for_gaps.append(candidate)
            except (DataValidationError, KeyError, TypeError, ValueError):
                invalid_rows += 1

        missing_rows = sum(gap.expected_candles for gap in detect_market_data_gaps(valid_for_gaps))
        if duplicate_rows:
            issues.append("DUPLICATE_TIMESTAMP")
        if missing_rows:
            issues.append("MISSING_CANDLES")
        if invalid_rows:
            issues.append("INVALID_OHLC_OR_VALUE")
        if incomplete_rows:
            issues.append("INCOMPLETE_CANDLE")
        if order_errors:
            issues.append("TIMESTAMP_NOT_STRICTLY_INCREASING")
        if timezone_errors:
            issues.append("TIMESTAMP_NOT_UTC")
        denominator = max(1, len(rows) + missing_rows)
        penalty = duplicate_rows + missing_rows + invalid_rows + incomplete_rows + order_errors + timezone_errors
        score = round(max(0.0, 100.0 * (1.0 - penalty / denominator)), 2)
        aware = [value.astimezone(timezone.utc) for value in timestamps if value.tzinfo is not None and value.utcoffset() is not None]
        return DataQualityReport(
            symbol.upper(), timeframe, min(aware) if aware else None, max(aware) if aware else None,
            len(rows), duplicate_rows, missing_rows, invalid_rows, score,
            incomplete_rows, order_errors, timezone_errors, tuple(issues),
        )

    @staticmethod
    def _mapping(row: Any) -> dict[str, Any]:
        names = (
            "timestamp", "symbol", "timeframe", "open", "high", "low", "close",
            "volume", "tick_volume", "spread", "is_closed", "source", "provider",
        )
        values = {name: _value(row, name) for name in names if _value(row, name) is not None}
        values.setdefault("is_closed", True)
        values.setdefault("source", str(_value(row, "provider", "unknown")))
        return values
