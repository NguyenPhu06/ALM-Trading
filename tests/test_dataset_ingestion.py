"""Labelled observations entering the dataset (section 9)."""
from dataclasses import replace
from datetime import timedelta

import pytest

from ai.dataset.versioning import FEATURE_VERSION, LABEL_VERSION, PREPROCESSING_VERSION
from ai.dataset.labels import LabelingEngine
from observation.ingestion import DatasetIngestor, IngestionRefusal
from observation.lifecycle import ObservationStatus
from observation.outcome import ForwardOutcomeEngine
from tests.phase14_helpers import NOW, candles, observation, outcome

LATER = NOW + timedelta(hours=1, minutes=1)


def labelled_pair():
    """A resolved observation with a real label attached."""
    record = observation(status=ObservationStatus.OBSERVING)
    engine = ForwardOutcomeEngine(labeler=LabelingEngine())
    result = engine.resolve(record, candles(14, start=NOW, step_minutes=5), now=LATER)
    advanced = (record.advance(ObservationStatus.HORIZON_REACHED)
                .advance(ObservationStatus.OUTCOME_CALCULATED)
                .advance(ObservationStatus.LABELED))
    return advanced, result.outcome


# ------------------------------------------------------------ happy path
def test_a_labelled_observation_is_accepted(memory_repository):
    record, result = labelled_pair()
    accepted = DatasetIngestor(memory_repository).ingest(record, result)
    assert accepted.accepted
    assert accepted.refusal is None
    assert memory_repository.labels[record.observation_id] is result.label


def test_the_dataset_version_records_all_three_versions():
    ingestor = DatasetIngestor()
    assert ingestor.dataset_version == (
        f"{FEATURE_VERSION}.{LABEL_VERSION}.{PREPROCESSING_VERSION}")


def test_the_result_reports_the_dataset_version():
    record, result = labelled_pair()
    assert DatasetIngestor().ingest(record, result).dataset_version == \
        DatasetIngestor().dataset_version


def test_the_row_is_marked_as_forward_observation_evidence():
    record, result = labelled_pair()
    assert DatasetIngestor().ingest(record, result).as_dict()["evidence"] == \
        "FORWARD_OBSERVATION"


# --------------------------------------------------------------- refusals
def test_an_unlabelled_observation_is_refused():
    record = observation(status=ObservationStatus.OBSERVING)
    result = DatasetIngestor().ingest(record, outcome())
    assert result.refusal is IngestionRefusal.NOT_LABELED


def test_an_outcome_without_a_label_is_refused():
    record = observation(status=ObservationStatus.LABELED)
    result = DatasetIngestor().ingest(record, outcome())
    assert result.refusal is IngestionRefusal.MISSING_LABEL


def test_a_feature_version_mismatch_is_refused():
    record, result = labelled_pair()
    stale = replace(record, feature_version="features_v0")
    refused = DatasetIngestor().ingest(stale, result)
    assert refused.refusal is IngestionRefusal.FEATURE_VERSION_MISMATCH
    assert refused.context["expected"] == FEATURE_VERSION


def test_a_label_version_mismatch_is_refused():
    record, result = labelled_pair()
    stale_label = replace(result.label, label_version="labels_v0")
    refused = DatasetIngestor().ingest(record, replace(result, label=stale_label))
    assert refused.refusal is IngestionRefusal.LABEL_VERSION_MISMATCH


def test_an_observation_without_an_entry_price_is_refused():
    record, result = labelled_pair()
    refused = DatasetIngestor().ingest(replace(record, entry_price=None), result)
    assert refused.refusal is IngestionRefusal.NO_ENTRY_PRICE


# ------------------------------------------------------------- duplicates
def test_the_same_observation_is_only_ingested_once(memory_repository):
    record, result = labelled_pair()
    ingestor = DatasetIngestor(memory_repository)
    assert ingestor.ingest(record, result).accepted
    second = ingestor.ingest(record, result)
    assert not second.accepted
    assert second.refusal is IngestionRefusal.DUPLICATE_ROW


def test_a_row_already_in_the_repository_is_a_duplicate(memory_repository):
    record, result = labelled_pair()
    memory_repository.labels[record.observation_id] = result.label
    fresh = DatasetIngestor(memory_repository)
    assert fresh.ingest(record, result).refusal is IngestionRefusal.DUPLICATE_ROW


def test_a_failed_write_does_not_mark_the_row_as_seen():
    class Broken:
        def dataset_row_exists(self, observation_id):
            return False

        def attach_label(self, observation_id, label, *, future_price=None):
            raise RuntimeError("database down")

    record, result = labelled_pair()
    ingestor = DatasetIngestor(Broken())
    with pytest.raises(RuntimeError):
        ingestor.ingest(record, result)
    assert not ingestor.seen(record.observation_id), "a failed write must be retryable"


def test_a_broken_duplicate_check_does_not_crash_ingestion():
    class Flaky:
        def dataset_row_exists(self, observation_id):
            raise RuntimeError("lookup failed")

        def attach_label(self, observation_id, label, *, future_price=None):
            return label

    record, result = labelled_pair()
    assert DatasetIngestor(Flaky()).ingest(record, result).accepted


def test_two_different_observations_are_both_accepted(memory_repository):
    ingestor = DatasetIngestor(memory_repository)
    first, result = labelled_pair()
    second = replace(first, observation_id="obs-second")
    assert ingestor.ingest(first, result).accepted
    assert ingestor.ingest(second, replace(result, observation_id="obs-second")).accepted
    assert len(memory_repository.labels) == 2
