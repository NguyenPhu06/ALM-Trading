"""Shared fixtures for the Phase 13 learning tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np

from ai.dataset import DatasetBuilder
from ai.model_registry import ModelRecord, ModelState, ModelTask

NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")


def observation(index: int, stamp: datetime, trend: int = 1, *, price: float = 1.1000,
                session: str = "LONDON") -> dict[str, Any]:
    """A Phase 12 feature snapshot, shaped as the observation cycle emits it."""
    label = "BULLISH" if trend > 0 else "BEARISH" if trend < 0 else "RANGING"
    structure = "HH" if trend > 0 else "LL" if trend < 0 else None
    regime = "BULL" if trend > 0 else "BEAR" if trend < 0 else "RANGE"
    return {
        "cycle_id": f"cycle-{index}", "symbol": "EURUSD", "timestamp": stamp,
        "market_data": {"mid_price": price, "bid": price - 0.00005,
                        "ask": price + 0.00005, "source": "mt5"},
        "spread": {"spread": 0.00010, "spread_percent": 0.00009, "state": "NORMAL"},
        "session": {"session": session},
        "regime": {"regime": regime, "htf_score": trend * 0.5, "ltf_score": trend * 0.3,
                   "conflict": False},
        "structure": {tf: {"trend": label, "structure": structure,
                           "bos": label if trend else None, "choch": None,
                           "swing_high": price + 0.0050, "swing_low": price - 0.0050}
                      for tf in TIMEFRAMES},
        "indicators": {tf: {"rsi": 50 + trend * 10, "adx": 25 + abs(trend) * 5,
                            "atr": 0.0012, "ichimoku_tenkan": price + trend * 0.0008,
                            "ichimoku_kijun": price, "price_above_cloud": trend > 0,
                            "price_below_cloud": trend < 0}
                       for tf in TIMEFRAMES},
        "volatility": {tf: {"value": 0.0011} for tf in TIMEFRAMES},
        "liquidity": {"observed": [{"event_type": "LIQUIDITY_SWEEP", "price": price}],
                      "inferred": [{"event_type": "LIQUIDITY_POOL", "price": price}]},
        "strategy": {"score": 70.0, "confidence": 0.65,
                     "status": "EXECUTABLE_SIMULATION", "direction": "LONG"},
        "dca_projection": {"levels_planned": 2, "total_volume": 0.03},
    }


def candles(count: int, *, start: datetime, step_minutes: int = 5,
            drift: float = 0.00002, base: float = 1.1000) -> list[dict[str, Any]]:
    rows = []
    for index in range(count):
        stamp = start + timedelta(minutes=step_minutes * (index + 1))
        price = base + drift * index
        rows.append({"timestamp": stamp, "open": price, "close": price + drift,
                     "high": price + abs(drift) + 0.0002,
                     "low": price - abs(drift) - 0.0002})
    return rows


def observation_series(count: int = 240, *, start: datetime | None = None,
                       step_hours: int = 1, seed: int = 5):
    """Observations whose forward move follows their own trend, plus matching candles."""
    rng = np.random.default_rng(seed)
    start = start or (NOW - timedelta(hours=count + 4))
    trends = rng.choice([-1, 0, 1], size=count)
    sessions = ["LONDON", "NEW_YORK", "ASIA"]

    observations = []
    future: list[dict[str, Any]] = []
    for index in range(count):
        stamp = start + timedelta(hours=step_hours * index)
        observations.append(observation(index, stamp, int(trends[index]),
                                        session=sessions[index % len(sessions)]))
        drift = float(trends[index]) * 0.00012 + float(rng.normal(0, 0.00003))
        future.extend(candles(12, start=stamp, step_minutes=5, drift=drift))
    future.sort(key=lambda row: row["timestamp"])
    return observations, future


def build_dataset(*, horizon: str = "30m", count: int = 240, minimum_rows: int = 50,
                  now: datetime | None = None):
    observations, future = observation_series(count)
    return DatasetBuilder(minimum_rows=minimum_rows).build(
        observations, future, horizon=horizon, now=now or NOW)


def model_record(model_id: str = "m1", **overrides: Any) -> ModelRecord:
    payload: dict[str, Any] = dict(
        model_id=model_id, model_version="multitask_mlp.v1", task=ModelTask(),
        feature_version="features_v1", label_version="labels_v1",
        training_dataset_version="ds-1", preprocessing_version="scaler_v1",
        state=ModelState.EXPERIMENTAL, edge_verdict="EDGE_DETECTED",
        baseline_comparison={"beats_all_baselines": True},
        test_metrics={"balanced_accuracy": 0.58, "log_loss": 0.85, "expectancy": 0.0005,
                      "max_drawdown": 0.02, "net_expectancy": 0.0004},
        calibration={"brier_score": 0.18},
        walk_forward_metrics={"mean_accuracy": 0.57, "stability": 0.85},
        regime_metrics={"worst_expectancy": 0.0002},
        session_metrics={"worst_expectancy": 0.0002},
    )
    payload.update(overrides)
    return ModelRecord(**payload)


def weaker_record(model_id: str = "m2") -> ModelRecord:
    return model_record(
        model_id,
        test_metrics={"balanced_accuracy": 0.50, "log_loss": 1.10, "expectancy": 0.0000,
                      "max_drawdown": 0.06, "net_expectancy": -0.0001},
        calibration={"brier_score": 0.30},
        walk_forward_metrics={"mean_accuracy": 0.49, "stability": 0.40},
        regime_metrics={"worst_expectancy": -0.0003},
        session_metrics={"worst_expectancy": -0.0003})
