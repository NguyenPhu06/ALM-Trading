from strategy.mtf import MultiTimeframeEngine
from tests.phase6_helpers import snapshot

def test_mtf_conflict_waits_for_alignment():
    result = MultiTimeframeEngine().build(snapshot(conflict=True))
    assert result.higher_timeframe_bias in {"BULLISH", "STRONG_BULLISH"}
    assert result.alignment == "WAIT_FOR_ALIGNMENT"
    assert "TIMEFRAME_CONFLICT:M15" in result.conflicts

