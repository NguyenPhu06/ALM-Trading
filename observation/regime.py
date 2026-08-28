"""Unified multi-timeframe market regime.

Six states, derived from evidence across D1 -> M5 with weighted authority. The
higher timeframes (D1/H4/H1) hold authority; M30/M15/M5 contribute setup context
and can never, on their own, set the regime. That rule is enforced structurally:
if the higher timeframes supply no evidence the regime is UNKNOWN, regardless of
what the lower timeframes say.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping

from config.settings import load_yaml

DEFAULT_WEIGHTS = {"D1": 0.32, "H4": 0.26, "H1": 0.20, "M30": 0.10, "M15": 0.08, "M5": 0.04}
DEFAULT_HTF = ("D1", "H4", "H1")
DEFAULT_LTF = ("M30", "M15", "M5")


class MarketRegime(StrEnum):
    STRONG_BULL = "STRONG_BULL"
    BULL = "BULL"
    RANGE = "RANGE"
    BEAR = "BEAR"
    STRONG_BEAR = "STRONG_BEAR"
    UNKNOWN = "UNKNOWN"


BULLISH_TOKENS = ("BULL", "HH", "HL", "UP")
BEARISH_TOKENS = ("BEAR", "LH", "LL", "DOWN")


def direction_of(value: Any) -> int:
    """+1 bullish, -1 bearish, 0 neutral or unknown."""
    text = str(value or "").upper()
    if any(token in text for token in BULLISH_TOKENS):
        return 1
    if any(token in text for token in BEARISH_TOKENS):
        return -1
    return 0


@dataclass(frozen=True, slots=True)
class TimeframeEvidence:
    timeframe: str
    available: bool
    trend: str | None = None
    structure: str | None = None
    bos: str | None = None
    choch: str | None = None

    @property
    def direction(self) -> float:
        """Trend and structure carry most of the weight; BOS/CHoCH refine it."""
        if not self.available:
            return 0.0
        return (0.35 * direction_of(self.trend) + 0.30 * direction_of(self.structure)
                + 0.25 * direction_of(self.bos) + 0.10 * direction_of(self.choch))

    def as_dict(self) -> dict[str, Any]:
        return {"timeframe": self.timeframe, "available": self.available, "trend": self.trend,
                "structure": self.structure, "bos": self.bos, "choch": self.choch,
                "direction": round(float(self.direction), 4)}


@dataclass(frozen=True, slots=True)
class RegimeResult:
    regime: MarketRegime
    score: float
    htf_score: float
    ltf_score: float
    conflict: bool
    evidence: dict[str, TimeframeEvidence] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def direction(self) -> int:
        if self.regime in {MarketRegime.STRONG_BULL, MarketRegime.BULL}:
            return 1
        if self.regime in {MarketRegime.STRONG_BEAR, MarketRegime.BEAR}:
            return -1
        return 0

    def as_dict(self) -> dict[str, Any]:
        return {"regime": str(self.regime), "score": round(self.score, 4),
                "htf_score": round(self.htf_score, 4), "ltf_score": round(self.ltf_score, 4),
                "conflict": self.conflict, "direction": self.direction,
                "reasons": list(self.reasons), "timestamp": self.timestamp,
                "timeframes": {name: item.as_dict() for name, item in self.evidence.items()}}


class MarketRegimeEngine:
    def __init__(self, *, weights: Mapping[str, float] | None = None,
                 strong_threshold: float | None = None,
                 directional_threshold: float | None = None,
                 htf: tuple[str, ...] | None = None, ltf: tuple[str, ...] | None = None):
        config = load_yaml().get("phase_12", {})
        self.weights = dict(weights or config.get("regime_weights") or DEFAULT_WEIGHTS)
        self.strong_threshold = float(
            strong_threshold if strong_threshold is not None
            else config.get("regime_strong_threshold", 0.60))
        self.directional_threshold = float(
            directional_threshold if directional_threshold is not None
            else config.get("regime_directional_threshold", 0.20))
        self.htf = tuple(htf or config.get("htf_authority") or DEFAULT_HTF)
        self.ltf = tuple(ltf or config.get("ltf_setup") or DEFAULT_LTF)

    def _weighted(self, evidence: Mapping[str, TimeframeEvidence], names) -> tuple[float, float]:
        total = available = 0.0
        for name in names:
            item = evidence.get(name)
            if item is None or not item.available:
                continue
            weight = self.weights.get(name, 0.0)
            total += weight * float(item.direction)
            available += weight
        return total, available

    def evaluate(self, evidence: Mapping[str, TimeframeEvidence]) -> RegimeResult:
        htf_total, htf_weight = self._weighted(evidence, self.htf)
        ltf_total, ltf_weight = self._weighted(evidence, self.ltf)
        htf_score = htf_total / htf_weight if htf_weight else 0.0
        ltf_score = ltf_total / ltf_weight if ltf_weight else 0.0

        reasons: list[str] = []
        # The lower timeframes may refine the regime, never decide it.
        if not htf_weight:
            reasons.append("NO_HIGHER_TIMEFRAME_EVIDENCE")
            return RegimeResult(MarketRegime.UNKNOWN, 0.0, 0.0, ltf_score, False,
                                dict(evidence), tuple(reasons))

        weight = htf_weight + ltf_weight
        score = (htf_total + ltf_total) / weight if weight else 0.0

        conflict = bool(htf_score and ltf_score and (htf_score > 0) != (ltf_score > 0))
        if conflict:
            reasons.append("LTF_CONFLICTS_WITH_HTF")

        # Direction comes from the higher timeframes; strength from the blend.
        if abs(htf_score) < self.directional_threshold:
            regime = MarketRegime.RANGE
            reasons.append("HTF_NOT_DIRECTIONAL")
        elif htf_score > 0:
            regime = (MarketRegime.STRONG_BULL
                      if score >= self.strong_threshold and not conflict else MarketRegime.BULL)
        else:
            regime = (MarketRegime.STRONG_BEAR
                      if score <= -self.strong_threshold and not conflict else MarketRegime.BEAR)
        reasons.append(f"HTF_SCORE_{htf_score:+.3f}")
        return RegimeResult(regime, score, htf_score, ltf_score, conflict,
                            dict(evidence), tuple(reasons))

    def from_snapshot(self, snapshot: Any) -> RegimeResult:
        """Build evidence from a MarketStateSnapshot produced by the intelligence engine."""
        evidence: dict[str, TimeframeEvidence] = {}
        for name in (*self.htf, *self.ltf):
            state = snapshot.timeframes.get(name) if snapshot else None
            if state is None:
                evidence[name] = TimeframeEvidence(name, False)
                continue
            evidence[name] = TimeframeEvidence(
                name, bool(getattr(state, "available", True)), getattr(state, "trend", None),
                getattr(state, "structure", None), getattr(state, "bos", None),
                getattr(state, "choch", None))
        return self.evaluate(evidence)
