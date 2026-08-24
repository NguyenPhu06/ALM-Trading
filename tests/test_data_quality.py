from __future__ import annotations

from datetime import datetime, timezone

import pytest

from data_quality import DataValidationError, MarketDataValidator
from data_sources.normalizer import CandleNormalizer


def raw_candle(timestamp: str = "2026-08-24T08:00:00Z") -> dict:
    return {
        "timestamp": timestamp, "symbol": "EUR/USD", "timeframe": "15",
        "open": "1.1000", "high": "1.1100", "low": "1.0900",
        "close": "1.1050", "volume": "100",
    }


def test_normalizes_to_utc_symbol_and_timeframe():
    candle = CandleNormalizer().normalize(raw_candle(), source="test")
    assert candle["symbol"] == "EURUSD"
    assert candle["timeframe"] == "M15"
    assert candle["timestamp"].tzinfo == timezone.utc


@pytest.mark.parametrize("field,value", [("high", "1.0"), ("low", "1.2"), ("volume", "-1")])
def test_rejects_invalid_ohlcv(field, value):
    raw = raw_candle()
    raw[field] = value
    with pytest.raises(DataValidationError):
        CandleNormalizer().normalize(raw, source="test")


def test_rejects_naive_or_missing_timestamp():
    with pytest.raises(DataValidationError):
        CandleNormalizer().normalize(raw_candle("2026-08-24T08:00:00"), source="test")
    raw = raw_candle()
    raw.pop("timestamp")
    with pytest.raises(DataValidationError):
        CandleNormalizer().normalize(raw, source="test")


def test_detects_duplicates_and_gaps_without_filling():
    normalizer = CandleNormalizer()
    candles = [
        normalizer.normalize(raw_candle("2026-08-24T08:00:00Z"), source="test"),
        normalizer.normalize(raw_candle("2026-08-24T08:00:00Z"), source="test"),
        normalizer.normalize(raw_candle("2026-08-24T08:30:00Z"), source="test"),
    ]
    validator = MarketDataValidator()
    assert len(validator.duplicate_keys(candles)) == 1
    assert len(validator.detect_gaps(candles)) == 1
    assert len(candles) == 3

