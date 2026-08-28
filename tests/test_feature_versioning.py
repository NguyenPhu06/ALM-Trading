"""Feature definitions are versioned and never change silently (section 4)."""
import pytest

from ai.dataset.features import FEATURE_GROUPS, FeatureExtractor
from ai.dataset.versioning import (
    FEATURE_VERSION, LABEL_VERSION, PREPROCESSING_VERSION, content_hash, dataset_id,
)
from tests.phase13_helpers import NOW, observation


def test_every_row_carries_a_feature_version():
    row = FeatureExtractor().extract(observation(0, NOW))
    assert row.feature_version == FEATURE_VERSION == "features_v1"


def test_feature_names_are_stable_and_ordered():
    first = FeatureExtractor().extract(observation(0, NOW))
    second = FeatureExtractor().extract(observation(1, NOW, trend=-1))
    assert first.names == second.names
    assert list(first.names) == sorted(first.names)


def test_the_same_snapshot_yields_the_same_vector():
    snapshot = observation(0, NOW)
    assert (FeatureExtractor().extract(snapshot).values
            == FeatureExtractor().extract(snapshot).values)


def test_all_six_timeframes_contribute_structure_and_indicators():
    names = FeatureExtractor().extract(observation(0, NOW)).names
    for timeframe in ("d1", "h4", "h1", "m30", "m15", "m5"):
        assert f"trend_{timeframe}" in names
        assert f"rsi_{timeframe}" in names
        assert f"adx_{timeframe}" in names
        assert f"atr_{timeframe}" in names
        assert f"ichimoku_tenkan_{timeframe}" in names


def test_structure_labels_are_encoded():
    names = FeatureExtractor().extract(observation(0, NOW)).names
    for label in ("hh", "hl", "lh", "ll"):
        assert f"{label}_m15" in names
    assert "bos_m15" in names and "choch_m15" in names


def test_liquidity_and_distance_features_are_present():
    names = FeatureExtractor().extract(observation(0, NOW)).names
    for name in ("liquidity_observed_count", "liquidity_inferred_count", "sweep_present",
                 "displacement_present", "rejection_present", "liquidity_pool_present",
                 "distance_previous_day_high", "distance_previous_day_low",
                 "distance_session_high", "distance_session_low",
                 "distance_support", "distance_resistance"):
        assert name in names, name


def test_session_and_clock_features_are_present():
    row = FeatureExtractor().extract(observation(0, NOW))
    mapping = row.as_mapping()
    assert mapping["session_london"] == 1.0
    assert "hour_of_day" in mapping and "day_of_week" in mapping
    assert mapping["hour_of_day"] == float(NOW.hour)


def test_strategy_and_dca_state_are_present():
    mapping = FeatureExtractor().extract(observation(0, NOW)).as_mapping()
    assert mapping["strategy_executable"] == 1.0
    assert mapping["dca_levels_planned"] == 2.0


def test_spread_and_volatility_features_are_present():
    mapping = FeatureExtractor().extract(observation(0, NOW)).as_mapping()
    assert mapping["spread"] > 0
    assert "volatility_m15" in mapping


def test_a_bullish_and_bearish_snapshot_differ():
    bull = FeatureExtractor().extract(observation(0, NOW, trend=1)).as_mapping()
    bear = FeatureExtractor().extract(observation(0, NOW, trend=-1)).as_mapping()
    assert bull["trend_m15"] == 1.0 and bear["trend_m15"] == -1.0
    assert bull["regime_bull"] == 1.0 and bear["regime_bear"] == 1.0


def test_missing_values_default_rather_than_producing_nan():
    sparse = {"symbol": "EURUSD", "timestamp": NOW}
    values = FeatureExtractor().extract(sparse).values
    assert all(value == value for value in values)


def test_features_are_grouped_for_explainability():
    row = FeatureExtractor().extract(observation(0, NOW))
    grouped = FeatureExtractor.grouped(row.names)
    for group in ("market_structure", "liquidity", "ichimoku", "rsi", "adx", "atr",
                  "session", "mtf"):
        assert group in grouped and grouped[group], group


def test_every_group_prefix_is_declared():
    assert set(FEATURE_GROUPS) >= {"market_structure", "liquidity", "ichimoku", "rsi",
                                   "adx", "atr", "session", "mtf"}


def test_dataset_ids_encode_their_versions_and_content():
    first = dataset_id(feature_version=FEATURE_VERSION, label_version=LABEL_VERSION,
                       symbols=["EURUSD"], timeframes=["M5"], horizon="1h", rows=100,
                       start=NOW, end=NOW)
    same = dataset_id(feature_version=FEATURE_VERSION, label_version=LABEL_VERSION,
                      symbols=["EURUSD"], timeframes=["M5"], horizon="1h", rows=100,
                      start=NOW, end=NOW)
    different = dataset_id(feature_version=FEATURE_VERSION, label_version=LABEL_VERSION,
                           symbols=["EURUSD"], timeframes=["M5"], horizon="4h", rows=100,
                           start=NOW, end=NOW)
    assert first == same and first != different
    assert first.startswith(f"{FEATURE_VERSION}.{LABEL_VERSION}.")


def test_content_hash_is_order_independent():
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_preprocessing_version_is_declared():
    assert PREPROCESSING_VERSION == "scaler_v1"
