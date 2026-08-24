from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal


def deterministic_m15_candles(
    count: int = 192,
    *,
    start: datetime = datetime(2026, 8, 20, tzinfo=timezone.utc),
) -> list[dict]:
    """Long, deterministic fixture for resampling/backtest tests; never production data."""
    rows = []
    for index in range(count):
        open_ = Decimal("1.10000") + Decimal(index % 12) * Decimal("0.00010")
        close = open_ + Decimal((index % 3) - 1) * Decimal("0.00005")
        high = max(open_, close) + Decimal("0.00020") + Decimal(index % 5) * Decimal("0.00001")
        low = min(open_, close) - Decimal("0.00020")
        rows.append({
            "timestamp": start + timedelta(minutes=15 * index),
            "symbol": "EURUSD", "timeframe": "M15",
            "open": open_, "high": high, "low": low, "close": close,
            "volume": Decimal(100 + index % 10), "is_closed": True,
            "source": "deterministic_test_fixture",
        })
    return rows
