import numpy as np

from ai.features import HistoricalFeatureSchema
from ai.inference import NeuralInferenceEngine
from ai.models import NumpyMLPClassifier
from ai.models.registry import ModelRegistryMetadata
from features.candles import candle_close_time
from features.intelligence import MarketIntelligenceEngine
from tests.phase4_helpers import mtf_candles
from tests.phase5_helpers import training_config


def test_inference_returns_prediction_only_and_structured_context():
    candles = mtf_candles()
    timestamp = candle_close_time(candles["M15"][-1])
    snapshot = MarketIntelligenceEngine().calculate("EURUSD", candles, as_of=timestamp)
    raw = HistoricalFeatureSchema.extract(snapshot)
    names = tuple(sorted(raw))
    scaler = {
        "feature_names": list(names), "means": {name: 0.0 for name in names},
        "standard_deviations": {name: 1.0 for name in names}, "fitted_split": "TRAIN",
    }
    model = NumpyMLPClassifier(len(names), training_config())
    metadata = ModelRegistryMetadata(
        model.model_version, "fixture.dataset.v1", HistoricalFeatureSchema.VERSION,
        ("2026-01-01", "2026-02-01"), ("2026-02-02", "2026-02-10"),
        ("2026-02-11", "2026-02-20"), model.config.as_dict(), {},
        "2026-08-24T00:00:00+00:00", names, scaler,
    )
    engine = NeuralInferenceEngine(model, metadata)
    prediction = engine.predict(snapshot)
    assert np.isclose(prediction.prob_up + prediction.prob_down + prediction.prob_neutral, 1.0)
    context = engine.decision_context(
        snapshot, rule_context={"rule_state": "OBSERVE"},
        risk_context={"maximum_exposure_enforced": True},
    )
    assert context.action is None
    assert context.prediction == prediction
    assert not hasattr(engine, "place_order")
    assert not hasattr(engine, "open_position")
    assert not hasattr(engine, "close_position")
