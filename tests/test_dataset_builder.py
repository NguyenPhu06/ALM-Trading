"""Dataset builder and the audit every dataset must carry (sections 9, 35)."""
from datetime import timedelta

import pytest

from ai.dataset import DatasetBuilder, LeakageCode
from ai.dataset.versioning import FEATURE_VERSION, LABEL_VERSION, PREPROCESSING_VERSION
from tests.phase13_helpers import NOW, build_dataset, observation_series


def test_a_dataset_is_built_from_forward_observations():
    dataset = build_dataset()
    assert dataset.ok and dataset.audit.row_count > 0
    assert dataset.feature_names and len(dataset.feature_names) > 100


def test_the_three_partitions_are_populated():
    dataset = build_dataset()
    assert len(dataset.train) and len(dataset.validation) and len(dataset.test)
    total = len(dataset.train) + len(dataset.validation) + len(dataset.test)
    assert total == dataset.audit.row_count


def test_the_audit_records_every_documented_field():
    audit = build_dataset().audit.as_dict()
    for field in ("dataset_id", "feature_version", "label_version", "start", "end",
                  "symbols", "timeframes", "row_count", "class_distribution",
                  "missing_values", "duplicate_count", "source", "created_at", "horizon"):
        assert field in audit, field


def test_the_audit_records_the_versions_in_use():
    audit = build_dataset().audit
    assert audit.feature_version == FEATURE_VERSION
    assert audit.label_version == LABEL_VERSION
    assert audit.preprocessing_version == PREPROCESSING_VERSION


def test_the_audit_records_the_class_distribution():
    distribution = build_dataset().audit.class_distribution
    assert set(distribution) == {"UP", "DOWN", "NEUTRAL"}
    assert sum(distribution.values()) == build_dataset().audit.row_count


def test_the_audit_records_the_source_and_date_range():
    audit = build_dataset().audit
    assert audit.source == "forward_observation"
    assert audit.start is not None and audit.end is not None
    assert audit.start <= audit.end


def test_the_dataset_id_is_deterministic_for_identical_input():
    first = build_dataset()
    second = build_dataset()
    assert first.dataset_id == second.dataset_id


def test_a_different_horizon_produces_a_different_dataset_id():
    assert build_dataset(horizon="30m").dataset_id != build_dataset(horizon="1h").dataset_id


def test_observations_without_an_elapsed_horizon_are_refused_not_included():
    """Recent observations cannot be labelled yet, and are counted as refusals."""
    observations, future = observation_series(60)
    dataset = DatasetBuilder(minimum_rows=1).build(
        observations, future, horizon="24h", now=NOW)
    assert dataset.refusals
    assert any("HORIZON_NOT_ELAPSED" in code or "NO_FUTURE_DATA" in code
               for code in dataset.refusals)


def test_too_few_rows_is_reported_as_insufficient():
    observations, future = observation_series(20)
    dataset = DatasetBuilder(minimum_rows=500).build(
        observations, future, horizon="30m", now=NOW)
    assert LeakageCode.INSUFFICIENT_ROWS in dataset.quality.codes
    assert not dataset.ok


def test_an_empty_observation_set_produces_an_empty_dataset():
    dataset = DatasetBuilder(minimum_rows=1).build([], [], horizon="1h", now=NOW)
    assert dataset.audit.row_count == 0 and not dataset.ok


def test_every_row_carries_its_regime_session_and_versions():
    dataset = build_dataset()
    row = dataset.train.rows[0]
    assert row.regime and row.session
    assert row.feature_version == FEATURE_VERSION
    assert row.label_version == LABEL_VERSION


def test_partition_targets_are_available_for_every_regression_head():
    partition = build_dataset().train
    for name in ("future_return", "future_mfe", "future_mae", "net_return",
                 "future_volatility"):
        assert len(partition.targets(name)) == len(partition)
