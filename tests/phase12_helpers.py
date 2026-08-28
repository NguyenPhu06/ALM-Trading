"""Shared fixtures for Phase 12 observation tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from execution.mt5.mock import FakeMT5Module, MockMT5ReadOnlyClient
from observation.cycle import ObservationCycle

NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")
DEMO_SERVER = "Exness-MT5Trial8"
REAL_TRADE_MODE = 2


def module(**kwargs: Any) -> FakeMT5Module:
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("server", DEMO_SERVER)
    return FakeMT5Module(**kwargs)


def client(**kwargs: Any) -> MockMT5ReadOnlyClient:
    connected = MockMT5ReadOnlyClient(module=module(**kwargs))
    connected.connect()
    return connected


def candle(timestamp: datetime, **overrides: Any) -> dict[str, Any]:
    row = {"timestamp": timestamp, "symbol": "EURUSD", "timeframe": "M15",
           "open": 1.1000, "high": 1.1020, "low": 1.0990, "close": 1.1010,
           "volume": 120, "spread": 0.0001, "is_closed": True, "source": "mt5"}
    row.update(overrides)
    return row


def series(count: int = 60, *, timeframe: str = "M15", step_minutes: int = 15,
           now: datetime = NOW) -> list[dict[str, Any]]:
    """Boundary-aligned closed candles, the shape a real feed produces."""
    step = step_minutes * 60
    anchor = int(now.timestamp()) // step * step
    return [candle(datetime.fromtimestamp(anchor - step * (count - index), tz=timezone.utc),
                   timeframe=timeframe)
            for index in range(count)]


def cycle_for(db_session, *, inference: Any = None, alerts: Any = None,
              repository: Any = None, mt5: Any = None, seed: bool = True) -> ObservationCycle:
    if seed:
        from tests.phase9_helpers import seed_market

        seed_market(db_session, now=NOW)
    return ObservationCycle(db_session, client=mt5 or client(), inference=inference,
                            alerts=alerts, repository=repository)
