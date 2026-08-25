from __future__ import annotations

import json
import tempfile
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from ai.datasets import (
    DatasetExporter, DatasetReadinessChecker, ExpandingWalkForward,
    HistoricalDatasetBuilder, TrainOnlyStandardizer,
)
from ai.datasets.split import ChronologicalSplitter
from ai.labels import MultiHorizonLabeler
from data_quality import HistoricalDataQualityEngine
from database.models import DatasetMetadataRecord, MarketFeature, MarketLabel
from database.repositories import MLDatasetRepository
from tests.phase4_helpers import BASE, candles, mtf_candles


@pytest.fixture(scope="module")
def artifact():
    return HistoricalDatasetBuilder(classification_threshold=0.0005).build("EURUSD", mtf_candles())


def test_historical_data_quality_reports_duplicates_gaps_invalid_and_incomplete():
    rows = candles("M15", 5)
    duplicate = dict(rows[1])
    invalid = dict(rows[2], close=rows[2]["high"] + 1)
    incomplete = dict(rows[4], is_closed=False)
    inspected = [rows[0], rows[1], duplicate, invalid, incomplete]
    report = HistoricalDataQualityEngine().inspect(inspected, symbol="EURUSD", timeframe="M15")
    assert report.total_rows == 5
    assert report.duplicate_rows == 1
    assert report.missing_rows >= 1
    assert report.invalid_rows == 1
    assert report.incomplete_rows == 1
    assert report.timestamp_order_errors >= 1
    assert report.quality_score < 100


def test_multihorizon_labels_and_configurable_classification():
    rows = candles("M15", 20)
    labels = MultiHorizonLabeler(classification_threshold=0.0001).generate(rows)
    first = labels[0]
    assert first.label_end_timestamp == rows[10]["timestamp"] + timedelta(minutes=15)
    assert first.future_return_1 == pytest.approx(float(rows[1]["close"] / rows[0]["close"] - 1))
    assert first.classification in {"UP", "DOWN", "NEUTRAL"}
    assert first.long_outcome in {"FAVORABLE", "ADVERSE", "MIXED", "NEUTRAL"}


def test_dataset_has_required_features_chronological_split_and_stats(artifact):
    assert artifact.metadata.feature_version == "phase4.features.v1"
    assert artifact.metadata.label_version == "phase4.labels.v1"
    assert artifact.metadata.feature_count == 58
    assert artifact.metadata.label_count == 9
    assert artifact.metadata.row_count == len(artifact.samples) > 20
    assert [sample.timestamp for sample in artifact.samples] == sorted(sample.timestamp for sample in artifact.samples)
    assert {sample.split for sample in artifact.samples} == {"TRAIN", "VALIDATION", "TEST"}
    required = {
        "d1_trend", "h4_structure", "h1_atr", "m30_adx", "m15_rsi", "m5_trend",
        "distance_to_previous_day_high", "distance_to_swing_low", "liquidity_sweep",
        "bos", "choch", "hh", "hl", "lh", "ll", "atr_percent",
        "volatility_regime", "session", "day_of_week", "hour",
    }
    assert required <= set(artifact.samples[0].features)
    assert artifact.statistics["total_samples"] == artifact.metadata.row_count


def test_scaler_is_fit_only_on_train():
    timestamps = [BASE + timedelta(minutes=index) for index in range(10)]
    split = ChronologicalSplitter(train_ratio=0.6, validation_ratio=0.2).split(timestamps)
    rows = [{"value": float(index)} for index in range(10)]
    changed_future = rows[:6] + [{"value": 1_000_000.0} for _ in range(4)]
    scaler = TrainOnlyStandardizer()
    assert scaler.fit(rows, split) == scaler.fit(changed_future, split)
    assert scaler.fit(rows, split).fitted_split == "TRAIN"


def test_walk_forward_windows_expand_without_shuffle():
    timestamps = [BASE + timedelta(days=index) for index in range(20)]
    windows = list(ExpandingWalkForward(
        initial_train_size=8, validation_size=3, test_size=2, step_size=2,
    ).windows(timestamps))
    assert len(windows) >= 2
    assert windows[0].train_start == windows[1].train_start
    assert windows[1].train_end > windows[0].train_end
    assert all(window.train_end < window.validation_start < window.test_start for window in windows)


def test_dataset_hash_is_reproducible(artifact):
    rebuilt = HistoricalDatasetBuilder(classification_threshold=0.0005).build("EURUSD", mtf_candles())
    assert rebuilt.metadata.dataset_id == artifact.metadata.dataset_id
    assert rebuilt.metadata.dataset_hash == artifact.metadata.dataset_hash
    assert rebuilt.metadata.schema_hash == artifact.metadata.schema_hash


def test_dataset_export_parquet_is_immutable_and_ready(artifact):
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        paths = DatasetExporter().export(artifact, directory)
        assert all(path.exists() for path in paths.values())
        assert DatasetExporter().export(artifact, directory) == paths
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        assert metadata["dataset_hash"] == artifact.metadata.dataset_hash
        report = DatasetReadinessChecker(minimum_samples=20).check_files(paths["metadata"])
        assert report.ready, report.reasons


def test_dataset_repository_is_versioned_and_idempotent(db_session, artifact):
    repository = MLDatasetRepository(db_session)
    first = repository.persist(artifact)
    second = repository.persist(artifact)
    assert first == {"features": len(artifact.samples), "labels": len(artifact.samples), "metadata": 1}
    assert second == {"features": 0, "labels": 0, "metadata": 0}
    assert db_session.query(MarketFeature).count() == len(artifact.samples)
    assert db_session.query(MarketLabel).count() == len(artifact.samples)
    assert db_session.query(DatasetMetadataRecord).count() == 1
    conflicting = replace(artifact.metadata, dataset_hash="different")
    with pytest.raises(ValueError, match="different immutable"):
        repository.persist(replace(artifact, metadata=conflicting))
