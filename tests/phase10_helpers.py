"""Shared fixtures for the Phase 10 MT5 read-only tests."""
from __future__ import annotations

from datetime import datetime, timezone

from execution.mt5.mock import (
    CONTEST_TRADE_MODE,
    DEMO_TRADE_MODE,
    REAL_TRADE_MODE,
    FakeMT5Module,
    MockMT5ReadOnlyClient,
    demo_position,
)

NOW = datetime(2026, 8, 26, 12, tzinfo=timezone.utc)
TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")

ALM_POSITION = dict(ticket=600002, magic=0, comment="ALM-paper-mirror")
EXTERNAL_POSITION = dict(ticket=600001, magic=0, comment="manual entry")


def module(**kwargs):
    kwargs.setdefault("now", NOW)
    return FakeMT5Module(**kwargs)


def connected_client(**kwargs) -> MockMT5ReadOnlyClient:
    client = MockMT5ReadOnlyClient(module=module(**kwargs))
    client.connect()
    return client


def positions(*rows) -> list[dict]:
    return [demo_position(**row) for row in (rows or (EXTERNAL_POSITION,))]
