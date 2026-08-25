from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from data_quality.validator import timeframe_delta


BASE = datetime(2026, 8, 20, tzinfo=timezone.utc)


def candles(timeframe: str, count: int, history_bars: int = 70) -> list[dict]:
    delta = timeframe_delta(timeframe)
    start = BASE - delta * history_bars
    cycle = (0, 5, -3, 4, -6, 2, 7, -4, 1, -7, 3, -1)
    output = []
    for index in range(count):
        price = Decimal("1.1000") + Decimal(cycle[index % len(cycle)]) * Decimal("0.0004")
        open_ = price - Decimal("0.00005")
        output.append({
            "timestamp": start + delta * index, "symbol": "EURUSD", "timeframe": timeframe,
            "open": open_, "high": price + Decimal("0.00025"),
            "low": open_ - Decimal("0.00025"), "close": price,
            "volume": Decimal(100 + index), "spread": Decimal("0.0001"),
            "is_closed": True, "source": "historical_test", "provider": "historical_test",
        })
    return output


def mtf_candles() -> dict[str, list[dict]]:
    return {
        "D1": candles("D1", 85), "H4": candles("H4", 100), "H1": candles("H1", 120),
        "M30": candles("M30", 130), "M15": candles("M15", 115),
        "M5": candles("M5", 300),
    }
