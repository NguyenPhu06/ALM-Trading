from dataclasses import replace
from datetime import timedelta
import pytest
from strategy import MultiTimeframeEngine, StrategyIntelligenceEngine
from tests.phase6_helpers import NOW, snapshot
from tests.test_strategy_engine import prediction

def test_future_timeframe_and_prediction_are_rejected():
    snap = snapshot()
    states = dict(snap.timeframes)
    states["H1"] = replace(states["H1"], timestamp=NOW+timedelta(hours=1))
    with pytest.raises(ValueError, match="future timeframe"):
        MultiTimeframeEngine().build(replace(snap, timeframes=states))
    with pytest.raises(ValueError, match="future prediction"):
        StrategyIntelligenceEngine().evaluate(snap, entry_price=1.1, prediction=prediction(NOW+timedelta(minutes=1)))

