from __future__ import annotations

from features.intelligence.models import MarketStateSnapshot
from strategy.models import MultiTimeframeSnapshot, TimeframeStrategyState


TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")
HTF = ("D1", "H4", "H1")


def _direction(value: str | None) -> int:
    text = (value or "").upper()
    if any(token in text for token in ("BULL", "HH", "HL")):
        return 1
    if any(token in text for token in ("BEAR", "LH", "LL")):
        return -1
    return 0


class HigherTimeframeBiasEngine:
    """Bias tổng hợp từ trend, structure, BOS và CHoCH; không dựa vào một indicator."""

    weights = {"D1": 0.45, "H4": 0.35, "H1": 0.20}

    def calculate(self, states: dict[str, TimeframeStrategyState]) -> tuple[str, float]:
        total = 0.0
        available_weight = 0.0
        for timeframe in HTF:
            state = states.get(timeframe)
            if state is None or state.timestamp is None:
                continue
            component = (
                0.35 * _direction(state.trend)
                + 0.30 * _direction(state.structure)
                + 0.25 * _direction(state.bos)
                + 0.10 * _direction(state.choch)
            )
            total += self.weights[timeframe] * component
            available_weight += self.weights[timeframe]
        score = total / available_weight if available_weight else 0.0
        label = "STRONG_BULLISH" if score >= .65 else "BULLISH" if score >= .2 else "STRONG_BEARISH" if score <= -.65 else "BEARISH" if score <= -.2 else "NEUTRAL"
        return label, round(score, 6)


class MultiTimeframeEngine:
    def __init__(self, bias_engine: HigherTimeframeBiasEngine | None = None):
        self.bias_engine = bias_engine or HigherTimeframeBiasEngine()

    def build(self, snapshot: MarketStateSnapshot) -> MultiTimeframeSnapshot:
        states: dict[str, TimeframeStrategyState] = {}
        for timeframe in TIMEFRAMES:
            source = snapshot.timeframes.get(timeframe)
            if source is None:
                states[timeframe] = TimeframeStrategyState(timeframe, None, "UNKNOWN", None, None, None, None, None, "UNKNOWN", {})
                continue
            if source.timestamp and source.timestamp > snapshot.timestamp:
                raise ValueError("future timeframe state cannot enter strategy snapshot")
            states[timeframe] = TimeframeStrategyState(
                timeframe, source.timestamp, source.trend, source.structure, source.swing_high,
                source.swing_low, source.bos, source.choch,
                str(source.volatility.get("state", source.regime)), dict(source.liquidity), dict(source.indicators),
            )
        bias, _ = self.bias_engine.calculate(states)
        htf_dir = _direction(bias)
        conflicts: list[str] = []
        for timeframe in ("M30", "M15", "M5"):
            direction = _direction(states[timeframe].structure or states[timeframe].trend)
            if htf_dir and direction and direction != htf_dir:
                conflicts.append(f"TIMEFRAME_CONFLICT:{timeframe}")
        alignment = "WAIT_FOR_ALIGNMENT" if conflicts else "ALIGNED" if htf_dir else "NEUTRAL"
        return MultiTimeframeSnapshot(snapshot.symbol, snapshot.timestamp, states, bias, alignment, tuple(conflicts))

