from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from data_quality import DataValidationError, MarketDataValidator


TIMEFRAME_ALIASES = {
    "1": "M1", "5": "M5", "15": "M15", "30": "M30", "60": "H1",
    "240": "H4", "1H": "H1", "4H": "H4", "1D": "D1", "D": "D1",
    "1W": "W1", "W": "W1",
}


def normalize_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise DataValidationError("missing or invalid timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataValidationError("timestamp must include timezone; naive timestamps are rejected")
    return parsed.astimezone(timezone.utc)


def normalize_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        raise DataValidationError("invalid symbol")
    normalized = re.sub(r"[./_-]", "", raw)
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,19}", normalized):
        raise DataValidationError("invalid symbol")
    return normalized


def normalize_timeframe(value: Any) -> str:
    raw = str(value or "").strip().upper()
    normalized = TIMEFRAME_ALIASES.get(raw, raw)
    if not re.fullmatch(r"(S[1-9][0-9]*|M[1-9][0-9]*|H[1-9][0-9]*|D[1-9][0-9]*|W[1-9][0-9]*|MN[1-9][0-9]*)", normalized):
        raise DataValidationError("invalid timeframe")
    return normalized


def normalize_decimal(value: Any, field: str, *, optional: bool = False) -> Decimal | None:
    if optional and (value is None or value == ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise DataValidationError(f"{field} must be numeric") from None
    if not result.is_finite():
        raise DataValidationError(f"{field} must be finite")
    return result


def normalize_closed_state(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    if isinstance(value, str) and value.strip().lower() in {"true", "1", "yes"}:
        return True
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no"}:
        return False
    raise DataValidationError("is_closed must be boolean")


class CandleNormalizer:
    def __init__(self, validator: MarketDataValidator | None = None):
        self.validator = validator or MarketDataValidator()

    def normalize(self, raw: dict[str, Any], *, source: str) -> dict[str, Any]:
        candle = {
            "timestamp": normalize_timestamp(raw.get("timestamp")),
            "symbol": normalize_symbol(raw.get("symbol")),
            "timeframe": normalize_timeframe(raw.get("timeframe")),
            "open": normalize_decimal(raw.get("open"), "open"),
            "high": normalize_decimal(raw.get("high"), "high"),
            "low": normalize_decimal(raw.get("low"), "low"),
            "close": normalize_decimal(raw.get("close"), "close"),
            "volume": normalize_decimal(raw.get("volume"), "volume", optional=True),
            "tick_volume": normalize_decimal(raw.get("tick_volume"), "tick_volume", optional=True),
            "spread": normalize_decimal(raw.get("spread"), "spread", optional=True),
            "is_closed": normalize_closed_state(raw.get("is_closed")),
            "source": source,
            "provider": str(raw.get("provider") or source),
            "provider_timestamp": normalize_timestamp(raw["provider_timestamp"]) if raw.get("provider_timestamp") else None,
            "source_timeframe": normalize_timeframe(raw["source_timeframe"]) if raw.get("source_timeframe") else None,
            "target_timeframe": normalize_timeframe(raw["target_timeframe"]) if raw.get("target_timeframe") else None,
            "resampling_method": str(raw["resampling_method"]) if raw.get("resampling_method") else None,
        }
        self.validator.validate_candle(candle)
        return candle
