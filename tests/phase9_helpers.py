"""Deterministic synthetic market for orchestration tests.

The generator produces an asymmetric triangle wave with an upward drift so the
swing detector finds strictly unique pivots and classifies them HH/HL. Tiny
per-bar jitter breaks the value ties that a symmetric wave would create.

This is test scaffolding, not a claim about market behaviour and not a trained
model: the AI leg is exercised with an explicit stub so that production still
requires a real registry model.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from ai.models.contracts import ModelPrediction
from data_sources.ingestion import MarketDataIngestionService
from data_sources.providers import MockMarketDataProvider

NOW = datetime(2026, 8, 25, 10, tzinfo=timezone.utc)
SOURCE = "mock-real"
STEP_MINUTES = {"D1": 1440, "H4": 240, "H1": 60, "M30": 30, "M15": 15, "M5": 5}
SEED_COUNTS = (("D1", 90), ("H4", 120), ("H1", 160), ("M30", 160), ("M15", 240), ("M5", 240))


def _triangle(index: int, up: int, down: int) -> float:
    period = up + down
    phase = index % period
    return phase / up if phase < up else (period - phase) / down


def candles(
    timeframe: str, count: int, *, symbol: str = "EURUSD", now: datetime = NOW,
    drift: float = 0.0002, amplitude: float = 0.0020, up: int = 7, down: int = 5,
    bearish: bool = False,
) -> list[dict]:
    minutes = STEP_MINUTES[timeframe]
    direction = -1 if bearish else 1
    rows = []
    for index in range(count):
        stamp = now - timedelta(minutes=minutes * (count - index))
        current = 1.10 + direction * drift * index + amplitude * _triangle(index, up, down)
        nxt = 1.10 + direction * drift * (index + 1) + amplitude * _triangle(index + 1, up, down)
        low, high = min(current, nxt), max(current, nxt)
        jitter = (index * 7 % 5) * 0.00001
        rows.append({
            "timestamp": stamp, "symbol": symbol, "timeframe": timeframe,
            "open": Decimal(str(round(current, 5))),
            "high": Decimal(str(round(high + 0.00012 + jitter, 5))),
            "low": Decimal(str(round(low - 0.00012 - jitter, 5))),
            "close": Decimal(str(round(nxt, 5))),
            "volume": Decimal("100"), "tick_volume": Decimal("200"), "spread": Decimal(".0001"),
            "is_closed": True, "source": SOURCE, "provider": SOURCE, "provider_timestamp": stamp,
        })
    return rows


def seed_market(session, *, symbol: str = "EURUSD", now: datetime = NOW, bearish: bool = False,
                counts=SEED_COUNTS) -> int:
    """Ingest closed candles through the real validation and ingestion path."""
    inserted = 0
    for timeframe, count in counts:
        rows = candles(timeframe, count, symbol=symbol, now=now, bearish=bearish)
        provider = MockMarketDataProvider(rows)
        provider.name = SOURCE
        report = MarketDataIngestionService(session, provider).import_historical(
            symbol, timeframe, rows[0]["timestamp"], rows[-1]["timestamp"])
        inserted += report.rows_inserted
    return inserted


class StubInference:
    """Stands in for a trained model so the inference leg can be tested.

    Production passes `inference=None`, which keeps the registry lookup and the
    existing MODEL_UNAVAILABLE behaviour when no model is registered.
    """

    def __init__(self, *, prob_up: float = 0.72, prob_down: float = 0.18, prob_neutral: float = 0.10,
                 model_version: str = "test_mlp.v1", feature_version: str = "phase4.features.v1",
                 offset: timedelta = timedelta(0)):
        self.prob_up = prob_up
        self.prob_down = prob_down
        self.prob_neutral = prob_neutral
        self.model_version = model_version
        self.feature_version = feature_version
        self.offset = offset

    def predict(self, snapshot) -> ModelPrediction:
        return ModelPrediction(
            snapshot.timestamp + self.offset, snapshot.symbol,
            self.prob_up, self.prob_down, self.prob_neutral,
            max(self.prob_up, self.prob_down, self.prob_neutral),
            self.model_version, self.feature_version,
        )


class AlwaysSimulate:
    """Strategy double used only to exercise the paper-execution leg."""

    def __init__(self, decision):
        self.decision = decision
        self.calls = 0

    def evaluate(self, snapshot, *, entry_price, prediction=None, require_even_hour=False):
        self.calls += 1
        return self.decision
