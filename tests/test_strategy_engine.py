from ai.models.contracts import ModelPrediction
from strategy import SetupStatus, StrategyIntelligenceEngine
from tests.phase6_helpers import NOW, snapshot

def prediction(timestamp=NOW):
    return ModelPrediction(timestamp, "EURUSD", .74, .16, .10, .74, "test-model", "phase4.features.v1")

def test_strategy_combines_context_and_only_simulates():
    result = StrategyIntelligenceEngine().evaluate(snapshot(), entry_price=1.10, prediction=prediction())
    assert result.decision in {"SIMULATE", "WAIT"}
    assert result.setup.status in {SetupStatus.READY, SetupStatus.EXECUTABLE_SIMULATION}
    assert "LIVE_EXECUTION" not in str(result)
    assert result.setup.neural_prediction["prob_up"] == .74

def test_timeframe_conflict_never_enters():
    result = StrategyIntelligenceEngine().evaluate(snapshot(conflict=True), entry_price=1.10, prediction=prediction())
    assert result.setup.status is SetupStatus.WATCH
    assert result.decision == "WAIT"

