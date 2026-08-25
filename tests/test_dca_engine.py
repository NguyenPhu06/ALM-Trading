from strategy import DCAEngine, DCAPlan

def test_dca_is_finite_and_stops_on_invalidation():
    plan = DCAPlan(3, .001, 1., 3., .02)
    assert DCAEngine().evaluate(plan, entries=1, exposure=1., drawdown=.005, adverse_distance=.002,
        regime_valid=True, structure_valid=True, risk_allowed=True).allowed
    blocked = DCAEngine().evaluate(plan, entries=1, exposure=1., drawdown=.005, adverse_distance=.002,
        regime_valid=True, structure_valid=False, risk_allowed=True)
    assert not blocked.allowed and "STRUCTURE_INVALIDATED" in blocked.reason

