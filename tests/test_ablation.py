from backtest.strategy_analysis import ablation_test

def test_ablation_reports_each_component_without_assuming_improvement():
    result = ablation_test(("RSI", "ADX", "Ichimoku", "Liquidity", "Structure", "Neural Network"), lambda parts: len(parts) * -.1)
    assert len(result) == 7
    assert result["Baseline + RSI"] < result["Baseline"]

