from strategy.scoring import ScoreInput, StrategyScoringEngine

def test_indicator_is_only_one_configurable_component():
    values = ScoreInput(1, 1, 1, 0, .7, 1, 1)
    result = StrategyScoringEngine().score(values, ["RSI_IS_FEATURE_ONLY"], ())
    assert result.components["indicator_alignment"] == 0
    assert result.score > 50

