"""Strategy conflict engine (sections 21 and 22).

When the signals disagree, which one was right? That question cannot be answered
by reasoning about the signals — only by recording the disagreement and looking
at what followed. This module detects conflicts, and measures the outcome of
each kind so that signal weights can be derived from evidence rather than
asserted.

Section 22's rule is the point: **do not hardcode signal weights.** The weights
this module produces come from out-of-sample outcomes and are reported with the
sample size behind them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping, Sequence

from research.metrics import PerformanceMetrics, evaluate
from research.models import ResearchObservation, require_forward_only

# The signals whose weights are researched, not assumed.
SIGNALS: tuple[str, ...] = ("market_structure", "liquidity", "ichimoku", "rsi", "adx",
                            "nn", "mtf_regime")

HTF = ("D1", "H4", "H1")
LTF = ("M30", "M15", "M5")

BULLISH = {"BULL", "BULLISH", "UP", "BUY", "LONG", "STRONG_BULL"}
BEARISH = {"BEAR", "BEARISH", "DOWN", "SELL", "SHORT", "STRONG_BEAR"}
WEAK = {"WEAK", "NEUTRAL", "RANGE", "FLAT", "NONE", "UNKNOWN"}


class ConflictType(StrEnum):
    TIMEFRAME_CONFLICT = "TIMEFRAME_CONFLICT"
    INDICATOR_CONFLICT = "INDICATOR_CONFLICT"
    LIQUIDITY_NN_CONFLICT = "LIQUIDITY_NN_CONFLICT"
    STRUCTURE_NN_CONFLICT = "STRUCTURE_NN_CONFLICT"
    WEAK_TREND = "WEAK_TREND"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Resolution(StrEnum):
    FOLLOWED_HTF = "FOLLOWED_HTF"
    FOLLOWED_LTF = "FOLLOWED_LTF"
    FOLLOWED_NN = "FOLLOWED_NN"
    FOLLOWED_LIQUIDITY = "FOLLOWED_LIQUIDITY"
    FOLLOWED_STRUCTURE = "FOLLOWED_STRUCTURE"
    NO_TRADE = "NO_TRADE"
    UNKNOWN = "UNKNOWN"


def direction_of(value: Any) -> int:
    text = str(value or "").strip().upper()
    if text in BULLISH:
        return 1
    if text in BEARISH:
        return -1
    return 0


@dataclass(frozen=True, slots=True)
class Conflict:
    observation_id: str
    conflict_type: ConflictType
    severity: Severity
    resolution: Resolution
    detail: str = ""
    outcome_net_pnl: float | None = None
    outcome_correct: bool | None = None
    signals: dict[str, Any] = field(default_factory=dict)

    @property
    def resolved_well(self) -> bool | None:
        """Did following that side actually pay, net of cost?"""
        if self.outcome_net_pnl is None:
            return None
        return self.outcome_net_pnl > 0

    def as_dict(self) -> dict[str, Any]:
        return {"observation_id": self.observation_id,
                "conflict_type": str(self.conflict_type),
                "severity": str(self.severity), "resolution": str(self.resolution),
                "detail": self.detail, "outcome_net_pnl": self.outcome_net_pnl,
                "outcome_correct": self.outcome_correct,
                "resolved_well": self.resolved_well, "signals": dict(self.signals)}


class ConflictEngine:
    """Detects disagreement between signals and records what followed."""

    def detect(self, observation: ResearchObservation) -> list[Conflict]:
        signals = dict(observation.signals or {})
        if not signals:
            return []
        found: list[Conflict] = []

        timeframe = self._timeframe_conflict(observation, signals)
        if timeframe:
            found.append(timeframe)
        indicator = self._indicator_conflict(observation, signals)
        if indicator:
            found.append(indicator)
        found.extend(self._pairwise(observation, signals))
        return found

    # ------------------------------------------------------------- detectors
    def _timeframe_conflict(self, observation: ResearchObservation,
                            signals: Mapping[str, Any]) -> Conflict | None:
        """D1/H4/H1 bullish while M15/M5 bearish, or the reverse."""
        htf = [direction_of(signals.get(name)) for name in HTF if name in signals]
        ltf = [direction_of(signals.get(name)) for name in LTF if name in signals]
        if not htf or not ltf:
            return None
        htf_direction = _consensus(htf)
        ltf_direction = _consensus(ltf)
        if htf_direction == 0 or ltf_direction == 0 or htf_direction == ltf_direction:
            return None
        severity = Severity.HIGH if len(htf) >= 3 and len(ltf) >= 2 else Severity.MEDIUM
        return self._build(observation, ConflictType.TIMEFRAME_CONFLICT, severity,
                           self._resolution(observation, htf_direction,
                                            Resolution.FOLLOWED_HTF,
                                            Resolution.FOLLOWED_LTF),
                           f"HTF={_name(htf_direction)} LTF={_name(ltf_direction)}",
                           signals)

    def _indicator_conflict(self, observation: ResearchObservation,
                            signals: Mapping[str, Any]) -> Conflict | None:
        """Ichimoku directional, RSI neutral, ADX weak — the classic non-signal."""
        ichimoku = direction_of(signals.get("ichimoku"))
        rsi_value = str(signals.get("rsi") or "").upper()
        adx_value = str(signals.get("adx") or "").upper()
        if not ichimoku:
            return None
        rsi_neutral = rsi_value in WEAK
        adx_weak = adx_value in WEAK
        if not (rsi_neutral and adx_weak):
            return None
        return self._build(observation, ConflictType.WEAK_TREND, Severity.MEDIUM,
                           Resolution.NO_TRADE,
                           f"ichimoku={_name(ichimoku)} rsi={rsi_value} adx={adx_value}",
                           signals)

    def _pairwise(self, observation: ResearchObservation,
                  signals: Mapping[str, Any]) -> list[Conflict]:
        found: list[Conflict] = []
        pairs = (("liquidity", "nn", ConflictType.LIQUIDITY_NN_CONFLICT,
                  Resolution.FOLLOWED_LIQUIDITY, Resolution.FOLLOWED_NN),
                 ("market_structure", "nn", ConflictType.STRUCTURE_NN_CONFLICT,
                  Resolution.FOLLOWED_STRUCTURE, Resolution.FOLLOWED_NN))
        for left, right, kind, left_resolution, right_resolution in pairs:
            if left not in signals or right not in signals:
                continue
            left_direction = direction_of(signals[left])
            right_direction = direction_of(signals[right])
            if not left_direction or not right_direction \
                    or left_direction == right_direction:
                continue
            found.append(self._build(
                observation, kind, Severity.HIGH,
                self._resolution(observation, left_direction, left_resolution,
                                 right_resolution),
                f"{left}={_name(left_direction)} {right}={_name(right_direction)}",
                signals))

        indicators = [direction_of(signals.get(name)) for name in ("ichimoku", "rsi", "adx")
                      if name in signals]
        directional = [value for value in indicators if value]
        if len(directional) >= 2 and len(set(directional)) > 1:
            found.append(self._build(observation, ConflictType.INDICATOR_CONFLICT,
                                     Severity.LOW, Resolution.UNKNOWN,
                                     "indicators disagree", signals))
        return found

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _resolution(observation: ResearchObservation, side: int,
                    followed: Resolution, other: Resolution) -> Resolution:
        taken = direction_of(observation.predicted)
        if not taken:
            return Resolution.NO_TRADE
        return followed if taken == side else other

    @staticmethod
    def _build(observation: ResearchObservation, kind: ConflictType, severity: Severity,
               resolution: Resolution, detail: str,
               signals: Mapping[str, Any]) -> Conflict:
        return Conflict(observation_id=observation.observation_id, conflict_type=kind,
                        severity=severity, resolution=resolution, detail=detail,
                        outcome_net_pnl=observation.net_pnl,
                        outcome_correct=observation.correct, signals=dict(signals))

    # ----------------------------------------------------------------- study
    def study(self, observations: Sequence[ResearchObservation], *,
              minimum_samples: int = 30) -> dict[str, Any]:
        rows = require_forward_only(observations)
        conflicts: list[Conflict] = []
        by_observation: dict[str, list[Conflict]] = {}
        for row in rows:
            found = self.detect(row)
            conflicts.extend(found)
            if found:
                by_observation[row.observation_id] = found

        by_type: dict[str, list[Conflict]] = {}
        by_resolution: dict[str, list[Conflict]] = {}
        for conflict in conflicts:
            by_type.setdefault(str(conflict.conflict_type), []).append(conflict)
            by_resolution.setdefault(str(conflict.resolution), []).append(conflict)

        conflicted_ids = set(by_observation)
        conflicted = [row for row in rows if row.observation_id in conflicted_ids]
        clean = [row for row in rows if row.observation_id not in conflicted_ids]

        return {
            "observations": len(rows),
            "conflicted_observations": len(conflicted),
            "conflicts": len(conflicts),
            "by_type": {name: _summarise(items, minimum_samples)
                        for name, items in sorted(by_type.items())},
            "by_resolution": {name: _summarise(items, minimum_samples)
                              for name, items in sorted(by_resolution.items())},
            "conflicted_performance": evaluate(
                conflicted, minimum_samples=minimum_samples).as_dict(),
            "clean_performance": evaluate(
                clean, minimum_samples=minimum_samples).as_dict(),
            "note": ("A conflict is a recorded disagreement plus what followed it. "
                     "It is not a rule, and nothing here changes a signal weight."),
        }


def _summarise(conflicts: Sequence[Conflict], minimum_samples: int) -> dict[str, Any]:
    resolved = [item for item in conflicts if item.outcome_net_pnl is not None]
    wins = [item for item in resolved if item.resolved_well]
    returns = [item.outcome_net_pnl for item in resolved]
    return {
        "count": len(conflicts),
        "win_rate": (len(wins) / len(resolved)) if resolved else None,
        "expectancy": (sum(returns) / len(returns)) if returns else None,
        "reliable": len(conflicts) >= minimum_samples,
        "severities": sorted({str(item.severity) for item in conflicts}),
    }


def _consensus(values: Sequence[int]) -> int:
    directional = [value for value in values if value]
    if not directional or len(set(directional)) > 1:
        return 0
    return directional[0]


def _name(direction: int) -> str:
    return "BULL" if direction > 0 else "BEAR" if direction < 0 else "NEUTRAL"
