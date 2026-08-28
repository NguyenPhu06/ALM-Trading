"""Multiple testing protection (section 16).

Test twenty strategies at the 5% level and one of them looks profitable by
chance alone. The ledger exists so that fact is visible rather than forgotten:
it counts every hypothesis tested, records how the winner was selected, and
adjusts the significance bar for the number of tries.

The ledger cannot make a false positive impossible. What it can do is refuse to
let the count go unrecorded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Sequence


class SelectionMethod(StrEnum):
    PRE_REGISTERED = "PRE_REGISTERED"
    BEST_OF_N = "BEST_OF_N"
    SEQUENTIAL = "SEQUENTIAL"
    EXPLORATORY = "EXPLORATORY"


@dataclass(frozen=True, slots=True)
class Hypothesis:
    experiment_id: str
    name: str
    p_value: float | None = None
    significant: bool = False
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"experiment_id": self.experiment_id, "name": self.name,
                "p_value": self.p_value, "significant": self.significant,
                "recorded_at": self.recorded_at.isoformat(), **self.context}


def bonferroni(alpha: float, tests: int) -> float:
    """The corrected per-test threshold. More tries, higher bar."""
    return alpha / max(int(tests), 1)


def benjamini_hochberg(p_values: Sequence[float], alpha: float = 0.05) -> dict[str, Any]:
    """Step-up FDR control: less conservative than Bonferroni, still honest."""
    values = [float(value) for value in p_values if value is not None]
    if not values:
        return {"alpha": alpha, "tests": 0, "threshold": None, "rejected": 0}
    ordered = sorted(values)
    count = len(ordered)
    threshold = None
    for index, value in enumerate(ordered, start=1):
        if value <= alpha * index / count:
            threshold = value
    return {"alpha": alpha, "tests": count, "threshold": threshold,
            "rejected": sum(1 for value in ordered
                            if threshold is not None and value <= threshold)}


@dataclass(frozen=True, slots=True)
class MultipleTestingReport:
    experiment_count: int
    hypotheses_tested: int
    selection_method: SelectionMethod
    alpha: float
    adjusted_alpha: float
    holdout_usage: int
    survivors: tuple[str, ...] = ()
    false_discovery: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @property
    def inflated(self) -> bool:
        """True when the number of tries is large enough to manufacture a winner."""
        return self.hypotheses_tested >= int(1 / self.alpha) if self.alpha else False

    def as_dict(self) -> dict[str, Any]:
        return {"experiment_count": self.experiment_count,
                "hypotheses_tested": self.hypotheses_tested,
                "selection_method": str(self.selection_method), "alpha": self.alpha,
                "adjusted_alpha": self.adjusted_alpha,
                "holdout_usage": self.holdout_usage,
                "survivors": list(self.survivors),
                "false_discovery": dict(self.false_discovery),
                "inflated": self.inflated, "warnings": list(self.warnings)}


class ExperimentLedger:
    """Counts every experiment run in a research session."""

    def __init__(self, *, alpha: float = 0.05,
                 selection_method: SelectionMethod = SelectionMethod.EXPLORATORY):
        self.alpha = float(alpha)
        self.selection_method = SelectionMethod(selection_method)
        self._hypotheses: list[Hypothesis] = []
        self._experiments: list[str] = []
        self.holdout_usage = 0

    # ------------------------------------------------------------------ write
    def record(self, result: Any, *, p_value: float | None = None,
               significant: bool | None = None) -> Hypothesis:
        """Record one experiment. Re-running the same id counts once."""
        experiment_id = str(getattr(result, "experiment_id", result))
        name = str(getattr(result, "name", experiment_id))
        if experiment_id not in self._experiments:
            self._experiments.append(experiment_id)
        hypothesis = Hypothesis(
            experiment_id=experiment_id, name=name, p_value=p_value,
            significant=bool(significant) if significant is not None else False)
        self._hypotheses.append(hypothesis)
        return hypothesis

    def record_holdout_use(self, note: str = "") -> int:
        """Section 17: every touch of the holdout is counted, not just the first."""
        self.holdout_usage += 1
        return self.holdout_usage

    def select(self, method: SelectionMethod) -> None:
        self.selection_method = SelectionMethod(method)

    # ------------------------------------------------------------------- read
    @property
    def experiment_count(self) -> int:
        """Distinct configurations tried."""
        return len(self._experiments)

    @property
    def hypotheses_tested(self) -> int:
        """Every test run, including repeats of the same configuration."""
        return len(self._hypotheses)

    @property
    def adjusted_alpha(self) -> float:
        return bonferroni(self.alpha, self.hypotheses_tested)

    def survivors(self) -> list[Hypothesis]:
        """Hypotheses that clear the *corrected* bar, not the naive one."""
        threshold = self.adjusted_alpha
        return [item for item in self._hypotheses
                if item.p_value is not None and item.p_value <= threshold]

    def report(self) -> MultipleTestingReport:
        warnings: list[str] = []
        if self.hypotheses_tested > self.experiment_count:
            warnings.append("REPEATED_TESTS_ON_SAME_CONFIGURATION")
        if self.selection_method is SelectionMethod.BEST_OF_N:
            warnings.append("BEST_OF_N_SELECTION_INFLATES_APPARENT_EDGE")
        if self.holdout_usage > 1:
            warnings.append(f"HOLDOUT_USED_{self.holdout_usage}_TIMES")
        naive = [item for item in self._hypotheses
                 if item.p_value is not None and item.p_value <= self.alpha]
        survivors = self.survivors()
        if naive and not survivors:
            warnings.append("NO_RESULT_SURVIVES_MULTIPLE_TESTING_CORRECTION")

        return MultipleTestingReport(
            experiment_count=self.experiment_count,
            hypotheses_tested=self.hypotheses_tested,
            selection_method=self.selection_method, alpha=self.alpha,
            adjusted_alpha=self.adjusted_alpha, holdout_usage=self.holdout_usage,
            survivors=tuple(item.name for item in survivors),
            false_discovery=benjamini_hochberg(
                [item.p_value for item in self._hypotheses if item.p_value is not None],
                alpha=self.alpha),
            warnings=tuple(warnings))

    def as_dict(self) -> dict[str, Any]:
        return {**self.report().as_dict(),
                "hypotheses": [item.as_dict() for item in self._hypotheses]}
