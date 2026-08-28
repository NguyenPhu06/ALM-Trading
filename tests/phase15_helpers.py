"""Shared fixtures for the Phase 15 research tests.

Observations here carry **variance**. A constant-return arm has no pooled
standard deviation, so no effect size can be formed and the significance tester
refuses to call it decisive — which is correct behaviour but useless as a
fixture. `series()` therefore draws from a seeded normal distribution.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from research.models import ResearchObservation

NOW = datetime(2026, 8, 29, 12, tzinfo=timezone.utc)
DEFAULT_SPREAD = 0.0001


def observation(index: int = 0, *, net: float = 0.0004, correct: bool | None = True,
                confidence: float | None = 0.62, regime: str = "BULL",
                previous_regime: str | None = None, session: str = "LONDON",
                timeframe: str = "M5", dca_levels: int = 0,
                exit_kind: str | None = "TIME_EXIT", liquidity_event: str | None = None,
                signals: dict[str, Any] | None = None, predicted: str = "UP",
                resolved_at: datetime | None = None, mae: float = -0.0003,
                mfe: float = 0.0009, margin_used: float | None = 100.0,
                **extra: Any) -> ResearchObservation:
    actual = predicted if correct else ("DOWN" if predicted == "UP" else "UP")
    return ResearchObservation(
        observation_id=f"obs-{index}",
        resolved_at=resolved_at or (NOW - timedelta(hours=index)),
        net_pnl=net, predicted=predicted,
        actual=actual if correct is not None else None, correct=correct,
        confidence=confidence, mae=mae, mfe=mfe, spread=DEFAULT_SPREAD,
        holding_time=3600.0, margin_used=margin_used, regime=regime,
        previous_regime=previous_regime, session=session, timeframe=timeframe,
        symbol="EURUSD", dca_levels=dca_levels, exit_kind=exit_kind,
        liquidity_event=liquidity_event, signals=dict(signals or {}), **extra)


def series(count: int, *, mean: float = 0.0004, deviation: float = 0.0006,
           seed: int = 11, start: int = 0, correct_rate: float = 0.6,
           **fields: Any) -> list[ResearchObservation]:
    """Observations with realistic variance, so effect sizes can be formed."""
    generator = random.Random(seed)
    rows = []
    for index in range(count):
        net = generator.gauss(mean, deviation)
        rows.append(observation(start + index, net=net,
                                correct=generator.random() < correct_rate, **fields))
    return rows


def flat(count: int, *, net: float = 0.0004, start: int = 0,
         **fields: Any) -> list[ResearchObservation]:
    """Constant returns — useful only where variance must be absent on purpose."""
    return [observation(start + index, net=net, **fields) for index in range(count)]


def arms(names: Sequence[str], *, means: dict[str, float] | None = None,
         count: int = 150, seed: int = 5, **fields: Any
         ) -> dict[str, list[ResearchObservation]]:
    """One arm per name, each with its own seed so the arms are independent."""
    means = means or {}
    return {name: series(count, mean=means.get(name, 0.0003), seed=seed + index,
                         start=index * 1000, **fields)
            for index, name in enumerate(names)}


def ablation_arms(*, count: int = 150, better: Sequence[str] = ("BASELINE+NN",),
                  worse: Sequence[str] = ("BASELINE+RSI",),
                  base: float = 0.0002) -> dict[str, list[ResearchObservation]]:
    from research.ablation import ABLATION_ARMS

    means = {}
    for name in ABLATION_ARMS:
        if name in better:
            means[name] = base + 0.0009
        elif name in worse:
            means[name] = base - 0.0009
        else:
            means[name] = base
    return arms(ABLATION_ARMS, means=means, count=count)


def registry_with(*records):
    from research.registry import StrategyRegistry

    registry = StrategyRegistry()
    for record in records:
        registry.register(record)
    return registry


def validated(registry, key: str):
    """Walk a strategy to VALIDATED, the only state promotion accepts."""
    from research.registry import StrategyStatus

    registry.transition(key, StrategyStatus.TESTING)
    return registry.transition(key, StrategyStatus.VALIDATED)


SIGNAL_SET = {"D1": "BULL", "H4": "BULL", "H1": "BULL", "M30": "BULL",
              "M15": "BULL", "M5": "BULL", "liquidity": "BULL",
              "market_structure": "BULL", "nn": "BULL", "ichimoku": "BULL",
              "rsi": "BULL", "adx": "BULL"}


def conflicting(**overrides: str) -> dict[str, str]:
    return {**SIGNAL_SET, **overrides}
