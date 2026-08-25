from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Callable, Sequence

from backtest.strategy_engine import StrategyBacktestEvent


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    train: tuple[int, int]
    validation: tuple[int, int]
    test: tuple[int, int]


def walk_forward_folds(size: int, *, train: int, validation: int, test: int, step: int | None = None) -> list[WalkForwardFold]:
    if min(train, validation, test) <= 0: raise ValueError("walk-forward windows must be positive")
    folds = []
    for start in range(0, size - train - validation - test + 1, step or test):
        a, b, c, d = start, start + train, start + train + validation, start + train + validation + test
        folds.append(WalkForwardFold((a, b), (b, c), (c, d)))
    return folds


def ablation_test(features: Sequence[str], evaluator: Callable[[frozenset[str]], float]) -> dict[str, float]:
    baseline = frozenset({"baseline"})
    result = {"Baseline": evaluator(baseline)}
    for feature in features:
        result[f"Baseline + {feature}"] = evaluator(baseline | {feature})
    return result


def randomized_control(events: Sequence[StrategyBacktestEvent], *, seed: int = 42, randomize_direction: bool = True) -> list[StrategyBacktestEvent]:
    rng = Random(seed)
    output = []
    for event in events:
        decision = rng.choice(("WAIT", "SIMULATE", "WAIT"))
        direction = rng.choice(("LONG", "SHORT")) if randomize_direction else event.direction
        output.append(StrategyBacktestEvent(event.timestamp, event.price, decision, direction, event.regime,
                                            event.session, event.d1_bias, event.h4_bias, event.timestamp))
    return output

