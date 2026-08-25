from strategy import RiskEngine

def test_risk_blocks_extreme_volatility_and_missing_model():
    result = RiskEngine().evaluate(data_quality_ok=True, model_available=False, volatility="EXTREME_VOLATILITY")
    assert not result.risk_allowed
    assert {"MODEL_UNAVAILABLE", "EXTREME_VOLATILITY"} <= set(result.reason_codes)

