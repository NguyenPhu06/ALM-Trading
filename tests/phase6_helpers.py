from datetime import datetime, timezone

from features.intelligence.models import ConfluenceScore, FeatureVector, MarketBias, MarketStateSnapshot, TimeframeIntelligence


NOW = datetime(2025, 1, 6, 10, 0, tzinfo=timezone.utc)


def snapshot(*, conflict=False, timestamp=NOW, extreme=False):
    states = {}
    for timeframe in ("D1", "H4", "H1", "M30", "M15", "M5"):
        bullish = not (conflict and timeframe == "M15")
        states[timeframe] = TimeframeIntelligence(
            timestamp, "EURUSD", timeframe, True, "BULLISH" if bullish else "BEARISH",
            "HL" if bullish else "LH", "BULLISH_BOS" if bullish else "BEARISH_BOS", None,
            1.11, 1.09, {"nearest_high": 1.11, "nearest_low": 1.09},
            {"direction": "BULLISH"} if timeframe == "M15" else None, None, None,
            {"direction": "BULLISH"} if timeframe == "M15" else None,
            {"rsi": 58., "adx": 28., "di_plus": 30., "di_minus": 15., "price_above_cloud": True},
            {"state": "EXTREME_VOLATILITY" if extreme and timeframe == "M15" else "NORMAL_VOLATILITY"},
            "LONDON", None, regime="TRENDING",
        )
    return MarketStateSnapshot(timestamp, "EURUSD", states, MarketBias.BULLISH, .8,
        ConfluenceScore(80., {}, (), ()), "WATCH", (), (), (), FeatureVector((), ()),
        market_regime={"higher_timeframe_bias": "BULLISH"}, data_quality={"valid": True})

