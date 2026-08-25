from __future__ import annotations

from dataclasses import dataclass

from strategy.models import StrategyConfidence, StrategyScore


DEFAULT_WEIGHTS = {
    "structure_alignment": .22,
    "liquidity_alignment": .18,
    "mtf_alignment": .22,
    "indicator_alignment": .12,
    "nn_alignment": .10,
    "volatility_quality": .08,
    "session_quality": .08,
}


@dataclass(frozen=True, slots=True)
class ScoreInput:
    structure_alignment: float
    liquidity_alignment: float
    mtf_alignment: float
    indicator_alignment: float
    nn_alignment: float
    volatility_quality: float
    session_quality: float


class StrategyScoringEngine:
    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or DEFAULT_WEIGHTS
        if set(self.weights) != set(DEFAULT_WEIGHTS) or sum(self.weights.values()) <= 0:
            raise ValueError("strategy scoring weights are incomplete")

    def score(self, values: ScoreInput, reasons: list[str], conflicts: tuple[str, ...]) -> StrategyScore:
        components = {name: max(0., min(1., float(getattr(values, name)))) for name in self.weights}
        denominator = sum(self.weights.values())
        weighted = {name: components[name] * weight / denominator * 100 for name, weight in self.weights.items()}
        result = sum(weighted.values())
        if conflicts:
            result *= .5
        return StrategyScore(round(result, 2), components, {k: round(v, 2) for k, v in weighted.items()}, tuple(reasons), conflicts)

    def confidence(self, values: ScoreInput, nn_confidence: float) -> StrategyConfidence:
        parts = {
            "market_structure_confidence": values.structure_alignment,
            "liquidity_confidence": values.liquidity_alignment,
            "mtf_confidence": values.mtf_alignment,
            "indicator_confidence": values.indicator_alignment,
            "nn_confidence": max(0., min(1., nn_confidence)),
            "volatility_confidence": values.volatility_quality,
        }
        final = sum(parts.values()) / len(parts)
        return StrategyConfidence(**parts, final_confidence=round(final, 4))

