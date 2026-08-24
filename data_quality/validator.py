from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any


logger = logging.getLogger(__name__)
SYMBOL_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,19}$")
TIMEFRAME_PATTERN = re.compile(r"^(S[1-9][0-9]*|M[1-9][0-9]*|H[1-9][0-9]*|D[1-9][0-9]*|W[1-9][0-9]*|MN[1-9][0-9]*)$")


class DataValidationError(ValueError):
    pass


def timeframe_delta(timeframe: str) -> timedelta:
    unit, amount_text = ("MN", timeframe[2:]) if timeframe.startswith("MN") else (timeframe[0], timeframe[1:])
    amount = int(amount_text)
    multipliers = {
        "S": timedelta(seconds=1), "M": timedelta(minutes=1), "H": timedelta(hours=1),
        "D": timedelta(days=1), "W": timedelta(weeks=1), "MN": timedelta(days=30),
    }
    return multipliers[unit] * amount


class MarketDataValidator:
    def validate_candle(self, candle: dict[str, Any]) -> None:
        errors: list[str] = []
        timestamp = candle.get("timestamp")
        if not isinstance(timestamp, datetime):
            errors.append("missing or invalid timestamp")
        elif timestamp.tzinfo is None or timestamp.utcoffset() is None:
            errors.append("timestamp must include timezone")
        if not SYMBOL_PATTERN.fullmatch(str(candle.get("symbol", ""))):
            errors.append("invalid symbol")
        if not TIMEFRAME_PATTERN.fullmatch(str(candle.get("timeframe", ""))):
            errors.append("invalid timeframe")
        if not isinstance(candle.get("is_closed", True), bool):
            errors.append("is_closed must be boolean")
        try:
            open_, high, low, close = (Decimal(str(candle[name])) for name in ("open", "high", "low", "close"))
            if high < open_:
                errors.append("high must be >= open")
            if high < close:
                errors.append("high must be >= close")
            if low > open_:
                errors.append("low must be <= open")
            if low > close:
                errors.append("low must be <= close")
            if high < low:
                errors.append("high must be >= low")
            if candle.get("volume") is not None and Decimal(str(candle["volume"])) < 0:
                errors.append("volume cannot be negative")
        except (KeyError, ValueError, TypeError, ArithmeticError):
            errors.append("OHLC/volume values must be numeric")
        if errors:
            message = "; ".join(dict.fromkeys(errors))
            logger.warning("data validation failure: %s", message)
            raise DataValidationError(message)

    def duplicate_keys(self, candles: Iterable[dict[str, Any]]) -> set[tuple[str, str, datetime]]:
        seen: set[tuple[str, str, datetime]] = set()
        duplicates: set[tuple[str, str, datetime]] = set()
        for candle in candles:
            key = (candle["symbol"], candle["timeframe"], candle["timestamp"])
            if key in seen:
                duplicates.add(key)
            seen.add(key)
        return duplicates

    def detect_gaps(self, candles: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        ordered = sorted(candles, key=lambda row: row["timestamp"])
        gaps: list[dict[str, Any]] = []
        for previous, current in zip(ordered, ordered[1:]):
            if previous["symbol"] != current["symbol"] or previous["timeframe"] != current["timeframe"]:
                continue
            expected = previous["timestamp"] + timeframe_delta(previous["timeframe"])
            if current["timestamp"] > expected:
                gaps.append({"after": previous["timestamp"], "before": current["timestamp"], "expected_next": expected})
        return gaps
