"""Champion / challenger comparison.

A challenger replaces the champion only if it wins on out-of-sample evidence, and
only after a human approves. Higher training accuracy counts for nothing here —
this module never even looks at training metrics.

Every criterion is reported, so a promotion decision shows exactly what it was
based on and where the challenger was weaker.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai.model_registry.records import ModelRecord

# Criterion -> (metric path, higher_is_better)
CRITERIA: dict[str, tuple[str, bool]] = {
    "test_balanced_accuracy": ("test_metrics.balanced_accuracy", True),
    "test_log_loss": ("test_metrics.log_loss", False),
    "test_brier": ("calibration.brier_score", False),
    "walk_forward_mean": ("walk_forward_metrics.mean_accuracy", True),
    "walk_forward_stability": ("walk_forward_metrics.stability", True),
    "expectancy": ("test_metrics.expectancy", True),
    "max_drawdown": ("test_metrics.max_drawdown", False),
    "worst_regime_expectancy": ("regime_metrics.worst_expectancy", True),
    "worst_session_expectancy": ("session_metrics.worst_expectancy", True),
    "net_of_costs_expectancy": ("test_metrics.net_expectancy", True),
}


def _resolve(record: ModelRecord, path: str) -> float | None:
    section, _, key = path.partition(".")
    payload = getattr(record, section, None)
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class CriterionResult:
    name: str
    champion: float | None
    challenger: float | None
    higher_is_better: bool
    winner: str

    @property
    def comparable(self) -> bool:
        return self.champion is not None and self.challenger is not None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "champion": self.champion, "challenger": self.challenger,
                "higher_is_better": self.higher_is_better, "winner": self.winner}


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    recommend_promotion: bool
    criteria: tuple[CriterionResult, ...]
    reasons: tuple[str, ...] = ()
    challenger_wins: int = 0
    champion_wins: int = 0
    ties: int = 0
    incomparable: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "recommend_promotion": self.recommend_promotion,
            "challenger_wins": self.challenger_wins, "champion_wins": self.champion_wins,
            "ties": self.ties, "incomparable": self.incomparable,
            "reasons": list(self.reasons),
            "criteria": [item.as_dict() for item in self.criteria], **self.details,
        }


class ChampionChallengerComparator:
    """Recommends, never promotes. Promotion still needs an ApprovalToken."""

    def __init__(self, *, required_margin: float = 0.0, minimum_wins: int = 6):
        self.required_margin = float(required_margin)
        self.minimum_wins = int(minimum_wins)

    def compare(self, champion: ModelRecord | None,
                challenger: ModelRecord) -> ComparisonResult:
        reasons: list[str] = []

        # Hard gates first: no amount of metric superiority overrides these.
        if challenger.edge_verdict != "EDGE_DETECTED":
            reasons.append("CHALLENGER_HAS_NO_EDGE")
        if not challenger.baseline_comparison.get("beats_all_baselines", False):
            reasons.append("CHALLENGER_DOES_NOT_BEAT_BASELINES")
        if challenger.state.value not in {"VALIDATED", "CANDIDATE"}:
            reasons.append(f"CHALLENGER_STATE_{challenger.state}")

        if champion is None:
            results = tuple(
                CriterionResult(name, None, _resolve(challenger, path), higher, "CHALLENGER")
                for name, (path, higher) in CRITERIA.items())
            if not reasons:
                reasons.append("NO_INCUMBENT_CHAMPION")
            return ComparisonResult(
                not [reason for reason in reasons if reason != "NO_INCUMBENT_CHAMPION"],
                results, tuple(reasons), len(results), 0, 0, 0,
                {"note": "first model for this task"})

        results: list[CriterionResult] = []
        challenger_wins = champion_wins = ties = incomparable = 0
        for name, (path, higher) in CRITERIA.items():
            champion_value = _resolve(champion, path)
            challenger_value = _resolve(challenger, path)
            if champion_value is None or challenger_value is None:
                winner = "INCOMPARABLE"
                incomparable += 1
            else:
                difference = challenger_value - champion_value
                if not higher:
                    difference = -difference
                if difference > self.required_margin:
                    winner, challenger_wins = "CHALLENGER", challenger_wins + 1
                elif difference < -self.required_margin:
                    winner, champion_wins = "CHAMPION", champion_wins + 1
                else:
                    winner, ties = "TIE", ties + 1
            results.append(CriterionResult(name, champion_value, challenger_value, higher, winner))

        if challenger_wins < self.minimum_wins:
            reasons.append(f"CHALLENGER_WINS_{challenger_wins}_BELOW_{self.minimum_wins}")
        if champion_wins > challenger_wins:
            reasons.append("CHAMPION_STILL_STRONGER")
        if incomparable > len(CRITERIA) // 2:
            reasons.append("TOO_MANY_INCOMPARABLE_CRITERIA")

        return ComparisonResult(not reasons, tuple(results), tuple(reasons),
                                challenger_wins, champion_wins, ties, incomparable)
