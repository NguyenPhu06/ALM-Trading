from tests.phase6_helpers import snapshot

def test_strategy_fixture_uses_confirmed_liquidity_sweep_contract():
    sweep = snapshot().timeframes["M15"].sweep
    assert sweep and sweep["direction"] == "BULLISH"

