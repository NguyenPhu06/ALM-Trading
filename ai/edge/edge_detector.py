"""Statistical edge detection over forward observations (sections 22, 23, 24).

The detector answers one question and refuses to answer it loosely: is there
evidence that this model or strategy has an edge? Four verdicts, because "no"
and "not yet" and "sometimes" are different answers:

    EDGE_DETECTED     positive net expectancy, beats every baseline, and holds
                      across periods, regimes and sessions
    UNSTABLE_EDGE     positive overall, but it comes from a subset — a real
                      finding, and not something to trade
    NO_EDGE           fails expectancy, significance or a baseline
    INSUFFICIENT_DATA too few samples to say anything

Positive PnL alone is never an edge. Every figure here is **net** of costs, and
the input must be forward-observation evidence: a backtest is refused by name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from ai.edge.evidence import EvidenceSource, require_forward
from ai.evaluation.segmented import trading_metrics
from ai.evaluation.significance import bootstrap_interval, period_stability
from config.settings import load_yaml


class EdgeVerdict(StrEnum):
    EDGE_DETECTED = "EDGE_DETECTED"
    NO_EDGE = "NO_EDGE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNSTABLE_EDGE = "UNSTABLE_EDGE"


# Section 23. Every one of these must be beaten before an edge may be claimed.
# `champion` is separate: there is not always a champion to beat.
REQUIRED_BASELINES: tuple[str, ...] = (
    "random", "majority", "buy_and_hold", "momentum", "rsi", "ichimoku", "adx", "regime",
)


@dataclass(frozen=True, slots=True)
class SegmentConsistency:
    dimension: str
    segments: dict[str, float]
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    evaluated: int = 0

    @property
    def consistent(self) -> bool:
        """Consistent means no evaluated segment loses money."""
        return self.evaluated > 0 and not self.negative

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "segments": dict(self.segments),
                "positive": list(self.positive), "negative": list(self.negative),
                "evaluated": self.evaluated, "consistent": self.consistent}


@dataclass(frozen=True, slots=True)
class EdgeReport:
    verdict: EdgeVerdict
    samples: int
    metrics: dict[str, Any] = field(default_factory=dict)
    baselines: dict[str, float] = field(default_factory=dict)
    beaten: tuple[str, ...] = ()
    not_beaten: tuple[str, ...] = ()
    consistency: dict[str, SegmentConsistency] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    evidence: EvidenceSource = EvidenceSource.FORWARD_OBSERVATION

    @property
    def edge(self) -> bool:
        """Only the unambiguous verdict counts as an edge."""
        return self.verdict is EdgeVerdict.EDGE_DETECTED

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": str(self.verdict), "edge": self.edge, "samples": self.samples,
            "metrics": dict(self.metrics), "baselines": dict(self.baselines),
            "beaten": list(self.beaten), "not_beaten": list(self.not_beaten),
            "consistency": {name: item.as_dict() for name, item in self.consistency.items()},
            "reasons": list(self.reasons), "evidence": str(self.evidence),
        }


class EdgeDetector:
    def __init__(self, *, minimum_samples: int | None = None,
                 minimum_segment_samples: int = 20, confidence_level: float | None = None,
                 bootstrap_samples: int | None = None, periods: int = 3):
        config = load_yaml().get("phase_13", {})
        self.minimum_samples = int(minimum_samples if minimum_samples is not None
                                   else config.get("minimum_samples_for_edge", 100))
        self.minimum_segment_samples = int(minimum_segment_samples)
        self.confidence_level = float(confidence_level if confidence_level is not None
                                      else config.get("confidence_level", 0.95))
        self.bootstrap_samples = int(bootstrap_samples if bootstrap_samples is not None
                                     else config.get("bootstrap_samples", 1000))
        self.periods = int(periods)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def net_returns(outcomes: Sequence[Any]) -> list[float]:
        """Net, never gross (section 7)."""
        values = []
        for outcome in outcomes:
            value = getattr(outcome, "net_hypothetical_pnl", None)
            if value is None and isinstance(outcome, Mapping):
                value = outcome.get("net_hypothetical_pnl")
            if value is not None:
                values.append(float(value))
        return values

    def _segment(self, outcomes: Sequence[Any], attribute: str,
                 dimension: str) -> SegmentConsistency:
        grouped: dict[str, list[float]] = {}
        for outcome in outcomes:
            key = _read(outcome, attribute)
            value = _read(outcome, "net_hypothetical_pnl")
            if key is None or value is None:
                continue
            grouped.setdefault(str(key), []).append(float(value))

        means: dict[str, float] = {}
        positive: list[str] = []
        negative: list[str] = []
        evaluated = 0
        for name, values in sorted(grouped.items()):
            mean = sum(values) / len(values)
            means[name] = mean
            if len(values) < self.minimum_segment_samples:
                # Too few samples to call the segment either way.
                continue
            evaluated += 1
            (positive if mean > 0 else negative).append(name)
        return SegmentConsistency(dimension, means, tuple(positive), tuple(negative), evaluated)

    # --------------------------------------------------------------- evaluate
    def evaluate(self, outcomes: Sequence[Any], *,
                 baselines: Mapping[str, float] | None = None,
                 champion_expectancy: float | None = None,
                 walk_forward_scores: Sequence[float] | None = None,
                 evidence: EvidenceSource | str = EvidenceSource.FORWARD_OBSERVATION,
                 seed: int = 42) -> EdgeReport:
        """Evaluate an edge claim. Retrospective evidence raises `EvidenceRefused`."""
        source = require_forward(evidence)
        returns = self.net_returns(outcomes)
        samples = len(returns)
        baselines = {str(name): float(value) for name, value in (baselines or {}).items()}

        regime = self._segment(outcomes, "regime", "regime")
        session = self._segment(outcomes, "session", "session")
        timeframe = self._segment(outcomes, "timeframe", "timeframe")
        consistency = {"regime": regime, "session": session, "timeframe": timeframe}

        if samples < self.minimum_samples:
            return EdgeReport(
                EdgeVerdict.INSUFFICIENT_DATA, samples,
                metrics={"samples": samples, "minimum_samples": self.minimum_samples},
                baselines=baselines, consistency=consistency,
                reasons=(f"SAMPLE_BELOW_MINIMUM_{self.minimum_samples}",), evidence=source)

        trading = trading_metrics(returns)
        interval = bootstrap_interval(returns, samples=self.bootstrap_samples,
                                      level=self.confidence_level, seed=seed)
        stability = period_stability(returns, periods=self.periods)
        walk_forward = _walk_forward_consistency(walk_forward_scores)

        metrics = {
            "samples": samples,
            "expectancy": trading.get("expectancy"),
            "win_rate": trading.get("win_rate"),
            "profit_factor": trading.get("profit_factor"),
            "net_pnl": sum(returns),
            "mean_net_return": sum(returns) / samples,
            "max_drawdown": trading.get("max_drawdown"),
            "average_win": trading.get("average_win"),
            "average_loss": trading.get("average_loss"),
            "confidence_interval": interval.as_dict(),
            "period_stability": stability,
            "walk_forward_consistency": walk_forward,
        }

        expectancy = float(metrics["expectancy"] or 0.0)
        beaten: list[str] = []
        not_beaten: list[str] = []
        for name in REQUIRED_BASELINES:
            if name not in baselines:
                not_beaten.append(f"{name}:MISSING")
                continue
            (beaten if expectancy > baselines[name] else not_beaten).append(name)
        if champion_expectancy is not None:
            baselines["champion"] = float(champion_expectancy)
            (beaten if expectancy > float(champion_expectancy)
             else not_beaten).append("champion")

        reasons: list[str] = []
        if expectancy <= 0:
            reasons.append("NEGATIVE_EXPECTANCY")
        if not interval.excludes_zero:
            reasons.append("CONFIDENCE_INTERVAL_INCLUDES_ZERO")
        if not_beaten:
            reasons.append("DOES_NOT_BEAT_BASELINES")
        if walk_forward is not None and not walk_forward["consistent"]:
            reasons.append("WALK_FORWARD_INCONSISTENT")

        # Segment inconsistency alone does not deny an edge — it downgrades it.
        unstable: list[str] = []
        if not stability.get("consistent_sign", False):
            unstable.append("PERIOD_SIGN_FLIPS")
        for name, segment in consistency.items():
            if segment.evaluated and not segment.consistent:
                unstable.append(f"{name.upper()}_INCONSISTENT")

        if reasons:
            return EdgeReport(EdgeVerdict.NO_EDGE, samples, metrics, baselines,
                              tuple(beaten), tuple(not_beaten), consistency,
                              tuple(reasons), source)
        if unstable:
            return EdgeReport(EdgeVerdict.UNSTABLE_EDGE, samples, metrics, baselines,
                              tuple(beaten), tuple(not_beaten), consistency,
                              tuple(unstable), source)
        return EdgeReport(EdgeVerdict.EDGE_DETECTED, samples, metrics, baselines,
                          tuple(beaten), tuple(not_beaten), consistency, (), source)


def _walk_forward_consistency(scores: Sequence[float] | None) -> dict[str, Any] | None:
    if not scores:
        return None
    values = [float(score) for score in scores]
    best = max(values)
    worst = min(values)
    ratio = (worst / best) if best else 0.0
    return {"windows": len(values), "min": worst, "max": best,
            "stability": ratio, "consistent": worst > 0 and ratio >= 0.5}


def _read(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    value = getattr(source, name, None)
    if value is None:
        context = getattr(source, "context", None)
        if isinstance(context, Mapping):
            return context.get(name)
    return value
