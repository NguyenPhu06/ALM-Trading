"""The scaler is fitted on TRAIN only (section 12)."""
import numpy as np
import pytest

from ai.dataset.quality import DatasetQualityChecker, LeakageCode
from ai.dataset.versioning import PREPROCESSING_VERSION
from tests.phase13_helpers import build_dataset


def test_the_scaler_records_that_it_was_fitted_on_train():
    dataset = build_dataset()
    assert dataset.scaler.fitted_split == "TRAIN"


def test_the_scaler_statistics_match_the_training_partition_only():
    dataset = build_dataset()
    train_matrix = dataset.train.matrix
    for index, name in enumerate(dataset.feature_names):
        assert dataset.scaler.means[name] == pytest.approx(train_matrix[:, index].mean(),
                                                           abs=1e-9)


def test_the_scaler_statistics_differ_from_whole_dataset_statistics():
    """If they matched, the scaler would have seen validation and test."""
    dataset = build_dataset()
    everything = np.vstack([dataset.train.matrix, dataset.validation.matrix,
                            dataset.test.matrix])
    differences = [abs(dataset.scaler.means[name] - everything[:, index].mean())
                   for index, name in enumerate(dataset.feature_names)]
    assert max(differences) > 0, "scaler means are identical to full-dataset means"


def test_scaling_train_yields_approximately_zero_mean():
    dataset = build_dataset()
    scaled = dataset.scaled(dataset.train)
    assert np.abs(scaled.mean(axis=0)).max() < 1e-6


def test_validation_and_test_reuse_the_training_scaler():
    dataset = build_dataset()
    scaled = dataset.scaled(dataset.validation)
    means = np.asarray([dataset.scaler.means[name] for name in dataset.feature_names])
    deviations = np.asarray([dataset.scaler.standard_deviations[name] or 1.0
                             for name in dataset.feature_names])
    expected = (dataset.validation.matrix - means) / deviations
    assert np.allclose(scaled, expected)


def test_the_leakage_checker_flags_a_scaler_fitted_on_too_many_rows():
    report = DatasetQualityChecker.check_scaler_leakage(scaler_rows=100, train_rows=70)
    assert not report.ok
    assert LeakageCode.FUTURE_SCALING_LEAKAGE in report.codes
    assert LeakageCode.FUTURE_NORMALIZATION_LEAKAGE in report.codes


def test_a_correctly_fitted_scaler_passes_the_checker():
    assert DatasetQualityChecker.check_scaler_leakage(scaler_rows=70, train_rows=70).ok


def test_the_preprocessing_version_is_recorded_on_the_dataset():
    dataset = build_dataset()
    assert dataset.audit.preprocessing_version == PREPROCESSING_VERSION
