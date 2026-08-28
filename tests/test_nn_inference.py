"""Neural-network inference: probabilities only, never an order."""
import inspect

import pytest

from ai.inference import NeuralInferenceEngine
from ai.models.contracts import ModelPrediction
from tests.phase9_helpers import StubInference


def test_a_prediction_carries_all_three_probabilities_and_metadata():
    from datetime import datetime, timezone
    from types import SimpleNamespace

    snapshot = SimpleNamespace(timestamp=datetime(2026, 8, 27, 12, tzinfo=timezone.utc),
                               symbol="EURUSD")
    prediction = StubInference().predict(snapshot)
    assert prediction.prob_up and prediction.prob_down and prediction.prob_neutral
    assert prediction.confidence and prediction.model_version and prediction.feature_version
    assert prediction.timestamp == snapshot.timestamp


def test_probabilities_are_bounded():
    from datetime import datetime, timezone

    with pytest.raises(ValueError):
        ModelPrediction(datetime(2026, 8, 27, tzinfo=timezone.utc), "EURUSD",
                        1.5, -0.2, 0.1, 0.9, "m", "f")


def test_a_naive_timestamp_is_refused():
    from datetime import datetime

    with pytest.raises(ValueError, match="timezone-aware"):
        ModelPrediction(datetime(2026, 8, 27), "EURUSD", 0.5, 0.3, 0.2, 0.5, "m", "f")


def test_the_inference_engine_has_no_execution_method():
    for name in ("send_order", "execute", "order_send", "place_order", "submit"):
        assert not hasattr(NeuralInferenceEngine, name), name


def test_the_inference_engine_only_predicts_and_describes():
    public = {name for name, _ in inspect.getmembers(NeuralInferenceEngine, inspect.isfunction)
              if not name.startswith("_")}
    assert public <= {"predict", "model_input", "decision_context"}


def test_the_engine_refuses_a_model_and_metadata_version_mismatch():
    from types import SimpleNamespace

    model = SimpleNamespace(model_version="a")
    metadata = SimpleNamespace(model_version="b", scaler={"feature_names": ()}, features=())
    with pytest.raises(ValueError, match="versions differ"):
        NeuralInferenceEngine(model, metadata)


def test_the_observation_cycle_discards_a_future_prediction(db_session):
    """A model that predicts ahead of its snapshot is dropped, never used."""
    from datetime import timedelta

    from tests.phase12_helpers import cycle_for

    cycle = cycle_for(db_session, inference=StubInference(offset=timedelta(minutes=30)))
    result = cycle.run("EURUSD")
    assert result.snapshot is not None
    assert result.snapshot.neural_network is None


def test_a_missing_model_is_never_substituted(db_session):
    from tests.phase12_helpers import cycle_for

    result = cycle_for(db_session, inference=None).run("EURUSD")
    assert result.snapshot.neural_network is None


def test_a_failing_model_does_not_stop_the_cycle(db_session):
    from tests.phase12_helpers import cycle_for

    class Exploding:
        def predict(self, snapshot):
            raise RuntimeError("model blew up")

    result = cycle_for(db_session, inference=Exploding()).run("EURUSD")
    assert not result.halted
    assert result.snapshot.neural_network is None


# --------------------------------- Phase 13: multi-task inference and thresholds
# The Phase 12 tests above cover the prediction-only boundary. These cover the
# multi-task engine, its thresholds, and the absence of any training path.

def _engine(**overrides):
    import numpy as np

    from ai.inference.multitask_engine import ConfidenceThresholds, MultiTaskInferenceEngine
    from ai.models.multitask import MultiTaskConfig, MultiTaskMLP

    names = ("trend_m15", "rsi_m15")
    model = MultiTaskMLP(len(names), MultiTaskConfig(epochs=1))
    return MultiTaskInferenceEngine(
        model, feature_names=names, means={n: 0.0 for n in names},
        deviations={n: 1.0 for n in names}, model_version="multitask_mlp.v1",
        feature_version="features_v1", model_id="m1",
        thresholds=ConfidenceThresholds(**overrides) if overrides else None)


def test_phase13_the_engine_has_no_training_method():
    from ai.inference.multitask_engine import MultiTaskInferenceEngine

    for name in ("fit", "train", "partial_fit", "update", "learn"):
        assert not hasattr(MultiTaskInferenceEngine, name), name


def test_phase13_inference_emits_every_documented_output():
    from tests.phase13_helpers import NOW, observation

    payload = _engine().predict_snapshot(observation(0, NOW)).as_dict()
    for name in ("direction_probability", "expected_return", "expected_mfe",
                 "expected_mae", "confidence", "model_version", "feature_version",
                 "timestamp"):
        assert name in payload, name


def test_phase13_inference_is_never_a_trade_instruction():
    from tests.phase13_helpers import NOW, observation

    payload = _engine().predict_snapshot(observation(0, NOW)).as_dict()
    assert payload["is_trade_instruction"] is False
    for forbidden in ("buy", "sell", "order", "action"):
        assert forbidden not in payload


def test_phase13_a_feature_version_mismatch_is_refused():
    import pytest as _pytest

    from tests.phase13_helpers import NOW, observation

    engine = _engine()
    engine.feature_version = "features_v2"
    with _pytest.raises(ValueError, match="feature version mismatch"):
        engine.predict_snapshot(observation(0, NOW))


def test_phase13_thresholds_come_from_configuration():
    from ai.inference.multitask_engine import ConfidenceThresholds

    thresholds = ConfidenceThresholds.from_config()
    for name in ("minimum_confidence", "minimum_probability",
                 "minimum_expected_return", "maximum_expected_mae"):
        assert isinstance(getattr(thresholds, name), float)


def test_phase13_low_confidence_fails_the_threshold_check():
    from ai.models.multitask import MultiTaskOutput

    output = MultiTaskOutput({"UP": 0.4, "DOWN": 0.35, "NEUTRAL": 0.25}, 0.002, 0.003,
                             -0.001, 0.5, 0.40)
    meets, reasons = _engine().evaluate_thresholds(output)
    assert not meets and "CONFIDENCE_BELOW_MINIMUM" in reasons


def test_phase13_a_neutral_prediction_never_meets_the_threshold():
    from ai.models.multitask import MultiTaskOutput

    output = MultiTaskOutput({"UP": 0.2, "DOWN": 0.1, "NEUTRAL": 0.7}, 0.002, 0.003,
                             -0.001, 0.5, 0.70)
    meets, reasons = _engine().evaluate_thresholds(output)
    assert not meets and "PREDICTED_NEUTRAL" in reasons


def test_phase13_a_small_expected_return_fails_the_threshold():
    from ai.models.multitask import MultiTaskOutput

    output = MultiTaskOutput({"UP": 0.8, "DOWN": 0.1, "NEUTRAL": 0.1}, 0.00001, 0.003,
                             -0.001, 0.5, 0.80)
    meets, reasons = _engine().evaluate_thresholds(output)
    assert not meets and "EXPECTED_RETURN_BELOW_MINIMUM" in reasons


def test_phase13_a_large_expected_mae_fails_the_threshold():
    from ai.models.multitask import MultiTaskOutput

    output = MultiTaskOutput({"UP": 0.8, "DOWN": 0.1, "NEUTRAL": 0.1}, 0.002, 0.003,
                             -0.05, 0.5, 0.80)
    meets, reasons = _engine().evaluate_thresholds(output)
    assert not meets and "EXPECTED_MAE_ABOVE_MAXIMUM" in reasons


def test_phase13_a_strong_prediction_meets_the_thresholds():
    from ai.models.multitask import MultiTaskOutput

    output = MultiTaskOutput({"UP": 0.85, "DOWN": 0.1, "NEUTRAL": 0.05}, 0.002, 0.003,
                             -0.001, 0.5, 0.85)
    meets, reasons = _engine().evaluate_thresholds(output)
    assert meets and reasons == ()


def test_phase13_thresholds_are_not_hardcoded_magic_numbers():
    """Every threshold is configurable and reported alongside the prediction."""
    from tests.phase13_helpers import NOW, observation

    payload = _engine(minimum_confidence=0.9).predict_snapshot(
        observation(0, NOW)).as_dict()
    assert payload["thresholds"]["minimum_confidence"] == 0.9
