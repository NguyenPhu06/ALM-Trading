import tempfile
from pathlib import Path

import numpy as np
import pytest

from ai.models import NumpyMLPClassifier
from ai.models.registry import ImmutableModelRegistry, ModelRegistryMetadata
from ai.training.experiments import JsonExperimentTracker
from tests.phase5_helpers import classification_data, training_config


def test_registry_is_immutable_loadable_and_writes_model_card():
    _, matrix, labels, _ = classification_data(45)
    config = training_config()
    model = NumpyMLPClassifier(matrix.shape[1], config)
    model.fit(matrix[:30], labels[:30], matrix[30:40], labels[30:40])
    names = tuple(f"feature_{index}" for index in range(matrix.shape[1]))
    scaler = {"feature_names": list(names), "means": {name: 0.0 for name in names},
              "standard_deviations": {name: 1.0 for name in names}, "fitted_split": "TRAIN"}
    metadata = ModelRegistryMetadata(
        model.model_version, "dataset.v1", "phase4.features.v1",
        ("2026-01-01", "2026-02-01"), ("2026-02-02", "2026-02-10"),
        ("2026-02-11", "2026-02-20"), config.as_dict(), {"accuracy": 0.5},
        "2026-08-24T00:00:00+00:00", names, scaler,
    )
    with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
        registry = ImmutableModelRegistry(Path(directory) / "models")
        path = registry.register(model, metadata)
        loaded, loaded_metadata = registry.load(model.model_version)
        assert np.array_equal(model.predict_proba(matrix[40:]), loaded.predict_proba(matrix[40:]))
        assert loaded_metadata == metadata
        assert (path / "MODEL_CARD.md").exists()
        with pytest.raises(FileExistsError):
            registry.register(model, metadata)
        experiment = JsonExperimentTracker(Path(directory) / "experiments").record(
            model_version=model.model_version, dataset_version="dataset.v1",
            feature_version="phase4.features.v1", features=names,
            hyperparameters=config.as_dict(), metrics={"accuracy": 0.5},
        )
        assert experiment.experiment_id.startswith("exp_")


# ----------------------------------------- Phase 13: lifecycle model registry
# The Phase 5 tests above cover the immutable NumPy artifact store. These cover
# the Phase 13 registry that decides which model is authoritative (section 22).

def _record(model_id="p13-1", **overrides):
    from tests.phase13_helpers import model_record

    return model_record(model_id, **overrides)


def _registry(tmp_path):
    from ai.model_registry import ModelRegistry

    return ModelRegistry(artifacts_path=str(tmp_path))


def test_phase13_a_record_carries_every_documented_field():
    payload = _record().as_dict()
    for field in ("model_id", "model_version", "feature_version",
                  "training_dataset_version", "preprocessing_version",
                  "training_timestamp", "validation_metrics", "test_metrics",
                  "walk_forward_metrics", "regime_metrics", "session_metrics", "state"):
        assert field in payload, field


def test_phase13_the_task_key_identifies_one_champion_slot():
    from ai.model_registry import ModelTask

    assert ModelTask("direction", "EURUSD", "M5").key == "direction:EURUSD:M5"
    assert ModelTask("direction", "GBPUSD", "M5").key != ModelTask().key


def test_phase13_artifacts_are_written_outside_the_database(tmp_path):
    store = _registry(tmp_path)
    record = store.register(_record("p13-art"))
    path = store.save_artifact("p13-art", {"parameters": [1, 2, 3]})
    assert path.exists() and path.suffix == ".json"
    assert store.get("p13-art").artifact_path == str(path)
    assert store.load_artifact("p13-art")["parameters"] == [1, 2, 3]


def test_phase13_artifacts_never_contain_a_credential(tmp_path):
    store = _registry(tmp_path)
    store.register(_record("p13-secret"))
    path = store.save_artifact("p13-secret", {
        "parameters": [1], "password": "hunter2", "nested": {"api_key": "x", "w": 2}})
    text = path.read_text(encoding="utf-8")
    assert "hunter2" not in text and "password" not in text and "api_key" not in text
    assert "\"w\": 2" in text


def test_phase13_scrub_removes_secret_keys_at_any_depth():
    from ai.model_registry import scrub_artifact

    cleaned = scrub_artifact({"a": 1, "token": "t", "inner": {"secret": "s", "b": 2}})
    assert cleaned == {"a": 1, "inner": {"b": 2}}


def test_phase13_the_summary_counts_every_state(tmp_path):
    from ai.model_registry import ModelState, ModelTask

    store = _registry(tmp_path)
    store.register(_record("p13-s1"))
    store.register(_record("p13-s2"))
    store.transition("p13-s2", ModelState.VALIDATED)
    summary = store.summary(ModelTask())
    assert summary["total"] == 2
    assert summary["by_state"]["EXPERIMENTAL"] == 1
    assert summary["by_state"]["VALIDATED"] == 1
    assert "p13-s2" in summary["challengers"]


def test_phase13_an_unknown_model_raises(tmp_path):
    import pytest as _pytest

    with _pytest.raises(KeyError):
        _registry(tmp_path).transition("missing", None)


def test_phase13_records_persist_to_the_database(db_session, tmp_path):
    from ai.model_registry import ModelRegistry
    from database.models import ModelRegistryRecord
    from database.repositories import LearningRepository

    store = ModelRegistry(artifacts_path=str(tmp_path),
                          repository=LearningRepository(db_session))
    store.register(_record("p13-db"))
    row = db_session.query(ModelRegistryRecord).one()
    assert row.model_id == "p13-db" and row.state == "EXPERIMENTAL"
    assert row.feature_version == "features_v1"
    assert row.task_key == "direction:EURUSD:M5"


def test_phase13_no_registry_table_stores_a_binary_or_credential():
    from database.base import Base

    for table in Base.metadata.sorted_tables:
        if table.name not in {"model_registry", "dataset_audits", "model_drift_events",
                              "retraining_requests"}:
            continue
        for column in table.columns:
            assert "blob" not in str(column.type).lower(), f"{table.name}.{column.name}"
            assert not any(token in column.name.lower()
                           for token in ("password", "secret", "credential"))
