from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ai.datasets import HistoricalDatasetBuilder
from ai.models import ModelInput
import pytest
from features.intelligence import MarketIntelligenceEngine
from tests.phase4_helpers import mtf_candles


def test_closed_htf_candle_is_not_visible_before_its_close():
    candle = {
        "timestamp": datetime(2026, 8, 20, 10, tzinfo=timezone.utc),
        "symbol": "EURUSD", "timeframe": "H1", "open": Decimal("1.1"),
        "high": Decimal("1.2"), "low": Decimal("1.0"), "close": Decimal("1.15"),
        "volume": Decimal("1"), "is_closed": True,
    }
    engine = MarketIntelligenceEngine()
    before_close = engine.calculate(
        "EURUSD", {"H1": [candle]}, as_of=datetime(2026, 8, 20, 10, 15, tzinfo=timezone.utc),
    )
    after_close = engine.calculate(
        "EURUSD", {"H1": [candle]}, as_of=datetime(2026, 8, 20, 11, tzinfo=timezone.utc),
    )
    assert before_close.timeframes["H1"].available is False
    assert after_close.timeframes["H1"].available is True


def test_feature_at_t_is_unchanged_when_future_candles_change():
    original = mtf_candles()
    changed = deepcopy(original)
    builder = HistoricalDatasetBuilder(classification_threshold=0.0005)
    first = builder.build("EURUSD", original)
    timestamp = first.samples[0].timestamp
    future = next(row for row in changed["D1"] if row["timestamp"] + timedelta(days=1) > timestamp)
    future["open"] += Decimal("0.01")
    future["high"] += Decimal("0.01")
    future["low"] += Decimal("0.01")
    future["close"] += Decimal("0.01")
    second = builder.build("EURUSD", changed)
    second_sample = next(sample for sample in second.samples if sample.timestamp == timestamp)
    assert first.samples[0].features == second_sample.features


def test_labels_are_the_only_rows_with_future_end_timestamp():
    artifact = HistoricalDatasetBuilder(classification_threshold=0.0005).build("EURUSD", mtf_candles())
    for sample in artifact.samples:
        assert sample.label.timestamp == sample.timestamp
        assert sample.label.label_end_timestamp > sample.timestamp
        assert all("future" not in name and "mfe" not in name and "mae" not in name for name in sample.features)


def test_phase5_model_input_rejects_label_or_future_fields():
    with pytest.raises(ValueError, match="labels or future"):
        ModelInput(
            datetime(2026, 8, 20, tzinfo=timezone.utc), "EURUSD", (1.0, 2.0),
            ("d1_trend", "future_return_5"),
            "phase4.features.v1", "fixture.v1",
        )
