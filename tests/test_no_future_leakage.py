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


# ------------------------------------- Phase 13: forward-observation leakage
# The Phase 4 tests above cover historical candle/indicator visibility. These
# cover the six leakage classes of the forward-observation dataset (section 8).
from datetime import timedelta
from types import SimpleNamespace

import pytest

from ai.dataset.quality import DatasetQualityChecker, LeakageCode
from ai.dataset.split import RandomSplitRefused, random_split
from tests.phase13_helpers import NOW, build_dataset


def row(timestamp, *, values=(1.0, 2.0), resolved=None, source=None, symbol="EURUSD"):
    return SimpleNamespace(timestamp=timestamp, symbol=symbol, values=values,
                           feature_version="features_v1", label_version="labels_v1",
                           label_resolved_at=resolved,
                           context={"source_timestamp": source} if source else {})


def test_a_label_resolving_before_its_observation_is_target_leakage():
    rows = [row(NOW, resolved=NOW - timedelta(minutes=5))]
    report = DatasetQualityChecker.check_target_leakage(rows)
    assert not report.ok and LeakageCode.FUTURE_TARGET_LEAKAGE in report.codes


def test_a_label_resolving_after_its_observation_is_clean():
    rows = [row(NOW, resolved=NOW + timedelta(hours=1))]
    assert DatasetQualityChecker.check_target_leakage(rows).ok


def test_a_feature_sourced_from_the_future_is_candle_and_indicator_leakage():
    rows = [row(NOW, source=NOW + timedelta(minutes=15))]
    report = DatasetQualityChecker.check_feature_causality(rows)
    assert not report.ok
    assert LeakageCode.FUTURE_CANDLE_LEAKAGE in report.codes
    assert LeakageCode.FUTURE_INDICATOR_LEAKAGE in report.codes


def test_a_scaler_fitted_beyond_train_is_scaling_and_normalization_leakage():
    report = DatasetQualityChecker.check_scaler_leakage(scaler_rows=120, train_rows=70)
    assert LeakageCode.FUTURE_SCALING_LEAKAGE in report.codes
    assert LeakageCode.FUTURE_NORMALIZATION_LEAKAGE in report.codes


def test_overlapping_splits_are_random_split_leakage():
    bounds = {"train": (NOW - timedelta(days=3), NOW),
              "validation": (NOW - timedelta(days=1), NOW + timedelta(days=1)),
              "test": (NOW + timedelta(days=1), NOW + timedelta(days=2))}
    report = DatasetQualityChecker.check_split_leakage(bounds)
    assert not report.ok and LeakageCode.RANDOM_SPLIT_LEAKAGE in report.codes


def test_non_overlapping_splits_are_clean():
    bounds = {"train": (NOW - timedelta(days=3), NOW - timedelta(days=2)),
              "validation": (NOW - timedelta(days=1), NOW - timedelta(hours=12)),
              "test": (NOW, NOW + timedelta(days=1))}
    assert DatasetQualityChecker.check_split_leakage(bounds).ok


def test_random_splitting_is_structurally_refused():
    with pytest.raises(RandomSplitRefused):
        random_split([NOW])


def test_out_of_order_rows_are_detected():
    rows = [row(NOW), row(NOW - timedelta(hours=1))]
    report = DatasetQualityChecker().check(rows)
    assert LeakageCode.NON_CHRONOLOGICAL in report.codes


def test_duplicate_rows_are_detected():
    rows = [row(NOW), row(NOW)]
    report = DatasetQualityChecker().check(rows)
    assert LeakageCode.DUPLICATE_ROW in report.codes


def test_mixed_feature_versions_are_detected():
    rows = [row(NOW), row(NOW + timedelta(hours=1))]
    rows[1].feature_version = "features_v2"
    report = DatasetQualityChecker().check(rows, feature_version="features_v1")
    assert LeakageCode.FEATURE_VERSION_MIXED in report.codes


def test_a_real_dataset_passes_every_leakage_check():
    dataset = build_dataset()
    assert dataset.quality.ok, dataset.quality.codes
    for code in (LeakageCode.FUTURE_TARGET_LEAKAGE, LeakageCode.FUTURE_CANDLE_LEAKAGE,
                 LeakageCode.RANDOM_SPLIT_LEAKAGE, LeakageCode.FUTURE_SCALING_LEAKAGE):
        assert code not in dataset.quality.codes


def test_every_label_resolves_strictly_after_its_observation():
    dataset = build_dataset()
    for partition in (dataset.train, dataset.validation, dataset.test):
        for item in partition.rows:
            assert item.label.resolved_at > item.timestamp
