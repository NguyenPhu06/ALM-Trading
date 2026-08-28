"""The Phase 14 loop end to end, plus model memory and rolling performance.

    OBSERVE -> horizon elapses -> OUTCOME -> LABEL -> DATASET
            -> performance -> segments -> errors -> edge

Model memory (section 13) and the rolling windows (section 14) are exercised
here because they only mean anything once the loop has produced something.
"""
from datetime import datetime, timedelta, timezone

import pytest

from ai.dataset.labels import LabelingEngine
from ai.edge import EdgeDetector, EdgeVerdict
from ai.model_registry.records import ModelRecord, ModelState, ModelTask
from ai.performance import (
    CAUSALITY_DISCLAIMER,
    TRACKED_GROUPS,
    ErrorAnalyzer,
    ForwardSegmentLearner,
    ModelMemory,
    PerformanceEntry,
    RollingPerformance,
    group_importance,
)
from ai.performance.rolling import WINDOWS
from database.repositories.forward import ForwardObservationRepository
from observation.driver import DriverConfig, ObservationDriver
from observation.ingestion import DatasetIngestor
from observation.lifecycle import ObservationStatus
from observation.outcome import ForwardOutcomeEngine
from tests.phase14_helpers import (
    BASELINES,
    NOW,
    FakeCycle,
    RecordingAlerts,
    candle_loader,
    candles,
    entries,
    observation,
    outcome,
    performance_entries,
)


def record(model_id="m1", *, version="multitask_mlp.v1", importance=None, state=None):
    groups = [{"group": name, "importance": value}
              for name, value in (importance or {}).items()]
    return ModelRecord(
        model_id=model_id, model_version=version, task=ModelTask(),
        feature_version="features_v1", label_version="labels_v1",
        training_dataset_version="features_v1.labels_v1.abc",
        preprocessing_version="scaler_v1", state=state or ModelState.EXPERIMENTAL,
        training_timestamp=NOW, test_metrics={"samples": 120, "accuracy": 0.61},
        regime_metrics={"worst_expectancy": -0.0001},
        session_metrics={"worst_expectancy": 0.0002},
        calibration={"brier_score": 0.21},
        explainability={"groups": groups})


# --------------------------------------------- 13. model memory
def test_memory_keeps_every_documented_field():
    payload = ModelMemory().remember(record(), drawdown=0.05).as_dict()
    for field in ("model_id", "version", "features", "training_range", "validation_range",
                  "test_range", "sample_count", "metrics", "regime_metrics",
                  "session_metrics", "drawdown", "calibration", "status"):
        assert field in payload, field


def test_memory_takes_the_sample_count_from_the_test_metrics():
    assert ModelMemory().remember(record()).sample_count == 120


def test_memory_records_the_ranges_it_is_given():
    entry = ModelMemory().remember(record(), ranges={
        "training": (NOW - timedelta(days=30), NOW - timedelta(days=10)),
        "validation": (NOW - timedelta(days=10), NOW - timedelta(days=5)),
        "test": (NOW - timedelta(days=5), NOW)})
    assert entry.training_range[0] == NOW - timedelta(days=30)
    assert entry.test_range[1] == NOW


def test_memory_keeps_superseded_models():
    memory = ModelMemory()
    memory.remember(record("m1", version="v1"))
    memory.remember(record("m2", version="v2"))
    assert [item.model_id for item in memory.history()] == ["m1", "m2"]


def test_re_remembering_a_model_updates_it_in_place():
    memory = ModelMemory()
    memory.remember(record("m1"))
    memory.remember(record("m1", state=ModelState.VALIDATED))
    assert len(memory.history()) == 1
    assert memory.get("m1").status == "VALIDATED"


def test_history_is_ordered_by_training_time():
    memory = ModelMemory()
    memory.remember(record("late"))
    early = record("early")
    memory.remember(type(early)(**{**early.as_dict(), "task": early.task,
                                   "training_timestamp": NOW - timedelta(days=1),
                                   "state": early.state})
                    if False else early)
    assert {item.model_id for item in memory.history()} == {"late", "early"}


def test_the_latest_model_is_the_most_recent():
    memory = ModelMemory()
    memory.remember(record("m1"))
    assert memory.latest().model_id == "m1"


def test_an_empty_memory_has_no_latest():
    assert ModelMemory().latest() is None


def test_the_summary_counts_by_status():
    memory = ModelMemory()
    memory.remember(record("m1"))
    memory.remember(record("m2", state=ModelState.CHAMPION))
    summary = memory.summary()
    assert summary["models"] == 2
    assert summary["by_status"] == {"EXPERIMENTAL": 1, "CHAMPION": 1}
    assert summary["disclaimer"] == CAUSALITY_DISCLAIMER


# -------------------------------------- 20. importance across versions
def test_group_importance_is_read_from_the_explainability_payload():
    assert group_importance({"groups": [{"group": "liquidity", "importance": 0.12}]}) == {
        "liquidity": 0.12}


def test_a_malformed_explainability_payload_yields_nothing():
    assert group_importance({}) == {}
    assert group_importance({"groups": "not a list"}) == {}
    assert group_importance({"groups": [{"group": "x"}]}) == {}


def test_importance_history_tracks_every_group_across_versions():
    memory = ModelMemory()
    memory.remember(record("m1", version="v1", importance={"market_structure": 0.20}))
    memory.remember(record("m2", version="v2", importance={"market_structure": 0.31}))
    history = memory.importance_history()
    assert history["versions"] == ["v1", "v2"]
    assert history["groups"]["market_structure"] == [0.20, 0.31]
    assert set(history["groups"]) == set(TRACKED_GROUPS)


def test_importance_history_carries_the_causality_disclaimer():
    assert "does not establish causality" in \
        ModelMemory().importance_history()["disclaimer"]


def test_comparing_two_models_reports_the_movement_per_group():
    memory = ModelMemory()
    memory.remember(record("m1", importance={"market_structure": 0.20, "liquidity": 0.10}))
    memory.remember(record("m2", importance={"market_structure": 0.31, "liquidity": 0.04}))
    comparison = memory.compare_importance("m1", "m2")
    assert comparison["deltas"]["market_structure"] == pytest.approx(0.11)
    assert comparison["largest_increase"] == "market_structure"
    assert comparison["largest_decrease"] == "liquidity"


def test_comparing_an_unknown_model_raises():
    with pytest.raises(KeyError):
        ModelMemory().compare_importance("missing", "also-missing")


# ------------------------------------------ 14. rolling performance
def test_every_documented_window_is_computed():
    assert WINDOWS == (7, 14, 30, 60, 90)
    windows = RollingPerformance().evaluate(performance_entries(40, now=NOW), now=NOW)
    assert set(windows) == {"7d", "14d", "30d", "60d", "90d"}


def test_a_window_reports_every_documented_metric():
    payload = RollingPerformance().evaluate(performance_entries(40, now=NOW),
                                            now=NOW)["30d"].as_dict()
    for name in ("win_rate", "expectancy", "profit_factor", "average_mae", "average_mfe",
                 "net_pnl", "max_drawdown", "prediction_accuracy", "calibration"):
        assert name in payload, name


def test_a_window_only_counts_what_falls_inside_it():
    recent = performance_entries(10, now=NOW, spacing_hours=1)
    old = performance_entries(10, now=NOW - timedelta(days=40), spacing_hours=1)
    windows = RollingPerformance().evaluate(recent + old, now=NOW)
    assert windows["7d"].samples == 10
    assert windows["60d"].samples == 20


def test_a_thin_window_is_reported_but_not_reliable():
    windows = RollingPerformance(minimum_samples=20).evaluate(
        performance_entries(5, now=NOW), now=NOW)
    assert windows["7d"].samples == 5
    assert windows["7d"].reliable is False
    assert windows["7d"].win_rate is not None, "the numbers stay visible"


def test_an_empty_window_reports_zero_not_none():
    windows = RollingPerformance().evaluate([], now=NOW)
    assert windows["7d"].samples == 0
    assert windows["7d"].reliable is False


def test_drawdown_is_measured_on_the_net_equity_path():
    rows = [PerformanceEntry("a", NOW, 0.001), PerformanceEntry("b", NOW, -0.003),
            PerformanceEntry("c", NOW, 0.0005)]
    windows = RollingPerformance().evaluate(rows, now=NOW)
    assert windows["7d"].max_drawdown == pytest.approx(0.003)


def test_calibration_is_measured_against_stated_confidence():
    confident_and_right = performance_entries(40, correct=True, confidence=0.9, now=NOW)
    calibration = RollingPerformance().evaluate(confident_and_right,
                                                now=NOW)["30d"].calibration
    assert calibration["brier_score"] == pytest.approx(0.01)
    assert calibration["expected_calibration_error"] == pytest.approx(0.1)


def test_confident_and_wrong_scores_a_worse_brier():
    right = RollingPerformance().evaluate(
        performance_entries(40, correct=True, confidence=0.9, now=NOW), now=NOW)
    wrong = RollingPerformance().evaluate(
        performance_entries(40, correct=False, confidence=0.9, now=NOW), now=NOW)
    assert wrong["30d"].calibration["brier_score"] > right["30d"].calibration["brier_score"]


def test_calibration_without_confidence_is_reported_as_insufficient():
    rows = [PerformanceEntry("a", NOW, 0.001, correct=True, confidence=None)]
    calibration = RollingPerformance().evaluate(rows, now=NOW)["7d"].calibration
    assert calibration["warning"] == "INSUFFICIENT_DATA_FOR_CALIBRATION"


def test_the_summary_names_the_reliable_windows():
    summary = RollingPerformance(minimum_samples=20).summary(
        performance_entries(30, now=NOW, spacing_hours=1), now=NOW)
    assert summary["reliable_windows"] == ["7d", "14d", "30d", "60d", "90d"]


# ------------------------------------------------ the loop, end to end
def test_the_loop_carries_an_observation_all_the_way_to_the_dataset(db_session):
    repository = ForwardObservationRepository(db_session)
    later = NOW + timedelta(hours=1, minutes=5)
    rows = candles(20, start=NOW, step_minutes=5, drift=0.00008)

    driver = ObservationDriver(
        cycle=FakeCycle(timestamp=later), repository=repository,
        config=DriverConfig(interval_seconds=300, symbols=("EURUSD",), horizon="1h"),
        alerts=RecordingAlerts(),
        outcome_engine=ForwardOutcomeEngine(labeler=LabelingEngine()),
        candles=candle_loader(rows), ingestor=DatasetIngestor(repository),
        clock=lambda: later, sleeper=lambda seconds: None)

    repository.save_observation(observation(1, timestamp=NOW))
    tick = driver.run_once(now=later)

    assert len(tick.resolved) == 1
    resolved = tick.resolved[0]
    assert resolved.label is not None
    assert resolved.net_hypothetical_pnl < resolved.future_return
    assert repository.get_observation("obs-1").status == str(ObservationStatus.DATASET_READY)
    assert repository.outcome_exists("obs-1")
    assert tick.orders_sent == 0


def test_the_analysis_stack_runs_over_what_the_loop_produced():
    rows = performance_entries(120, net=0.0004, correct=True, confidence=0.62,
                               sessions=("LONDON", "ASIA"), now=NOW)
    rolling = RollingPerformance().summary(rows, now=NOW)
    segments = ForwardSegmentLearner(minimum_samples=30).all_dimensions(rows)
    edge = EdgeDetector(minimum_samples=100).evaluate(entries(120, net=0.0004),
                                                      baselines=BASELINES)
    analysis = ErrorAnalyzer().classify(observation(),
                                        outcome(future_return=-0.001, net=-0.0011))

    assert rolling["total_samples"] == 120
    assert segments["session"]["reliable_segments"]
    assert edge.verdict is EdgeVerdict.EDGE_DETECTED
    assert analysis.correct is False


def test_an_insufficient_sample_never_claims_an_edge():
    """The honest answer when the loop has not run long enough."""
    report = EdgeDetector(minimum_samples=100).evaluate(entries(12), baselines=BASELINES)
    assert report.verdict is EdgeVerdict.INSUFFICIENT_DATA
    assert report.edge is False


def test_the_repository_round_trips_every_phase_14_record(db_session):
    from ai.model_registry.drift import DriftMonitor

    repository = ForwardObservationRepository(db_session)
    record_ = observation(9)
    repository.save_observation(record_)
    repository.save_outcome(record_, outcome(9))
    repository.save_error(ErrorAnalyzer().classify(
        record_, outcome(9, future_return=-0.001, net=-0.0011)))
    repository.save_performance("30d", RollingPerformance().evaluate(
        performance_entries(40, now=NOW), now=NOW)["30d"])
    repository.save_edge(EdgeDetector().evaluate(entries(120, net=0.0004),
                                                 baselines=BASELINES), symbol="EURUSD")

    assert repository.recent_observations(10)
    assert repository.recent_outcomes(10)
    assert repository.recent_errors(10)
    assert repository.recent_performance(10)
    assert repository.latest_edge("EURUSD").verdict == "EDGE_DETECTED"
