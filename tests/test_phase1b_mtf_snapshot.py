from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from features.liquidity import LiquidityEventData
from features.mtf import MTFStructureAnalyzer
from features.snapshot import create_feature_snapshot
from features.structure import StructureBias, StructureEventData


NOW = datetime(2026, 8, 20, 14, tzinfo=timezone.utc)


def event(timeframe, kind, direction, price="1.1"):
    return StructureEventData(NOW, "EURUSD", timeframe, kind, direction, Decimal(price))


def test_mtf_keeps_htf_bias_separate_from_ltf_retracement():
    events = {
        "D1": [event("D1", "BEARISH_BOS", "BEARISH") for _ in range(2)],
        "H4": [event("H4", "LL", "BEARISH"), event("H4", "LH", "BEARISH")],
        "H1": [event("H1", "BEARISH_BOS", "BEARISH")],
        "M15": [event("M15", "BULLISH_BOS", "BULLISH")],
    }
    result = MTFStructureAnalyzer().calculate(events)
    assert result.htf_bias in {StructureBias.BEARISH, StructureBias.STRONG_BEARISH}
    assert result.ltf_structure is StructureBias.BULLISH


def test_snapshot_excludes_future_events_and_indicators():
    candle = {"timestamp": NOW, "symbol": "EURUSD", "timeframe": "M15", "close": Decimal("1.10")}
    future = NOW.replace(hour=15)
    structure = [event("M15", "BEARISH_BOS", "BEARISH"), StructureEventData(future, "EURUSD", "M15", "BULLISH_CHOCH", "BULLISH", Decimal("1.2"))]
    liquidity = [
        LiquidityEventData(NOW, "EURUSD", "M15", "LIQUIDITY_LEVEL", "HIGH", Decimal("1.2")),
        LiquidityEventData(NOW, "EURUSD", "M15", "LIQUIDITY_LEVEL", "LOW", Decimal("1.0")),
    ]
    snapshot = create_feature_snapshot(candle, structure, liquidity)
    assert snapshot["last_bos"] == "BEARISH" and snapshot["last_choch"] is None
    assert snapshot["nearest_liquidity_high"] == Decimal("1.2")
    assert "rsi" not in snapshot and "adx" not in snapshot and "ichimoku" not in snapshot
