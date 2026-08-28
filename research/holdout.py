"""Holdout protection (section 17).

The final period of data is set aside and must stay untouched until the very
end. The failure mode this guards against is not malice — it is the researcher
who checks the holdout, adjusts one parameter, and checks again. After three
such rounds the holdout is training data wearing a different name.

`HoldoutGuard` cannot physically stop a second look. What it does is make every
look **counted and visible**, and refuse to call a result final once the budget
is spent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from config.settings import load_yaml
from research.models import ResearchObservation


class HoldoutViolation(RuntimeError):
    """Raised when research reads holdout data it is not allowed to read."""


@dataclass(frozen=True, slots=True)
class HoldoutSplit:
    research_end: datetime
    holdout_start: datetime
    holdout_end: datetime
    research_rows: int
    holdout_rows: int

    @property
    def ratio(self) -> float:
        total = self.research_rows + self.holdout_rows
        return (self.holdout_rows / total) if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {"research_end": self.research_end.isoformat(),
                "holdout_start": self.holdout_start.isoformat(),
                "holdout_end": self.holdout_end.isoformat(),
                "research_rows": self.research_rows, "holdout_rows": self.holdout_rows,
                "holdout_ratio": self.ratio}


@dataclass
class HoldoutAccess:
    reason: str
    at: datetime
    rows: int

    def as_dict(self) -> dict[str, Any]:
        return {"reason": self.reason, "at": self.at.isoformat(), "rows": self.rows}


class HoldoutGuard:
    """Splits chronologically and counts every read of the reserved tail."""

    def __init__(self, *, ratio: float | None = None, budget: int | None = None,
                 ledger: Any = None):
        config = load_yaml().get("phase_15", {}).get("holdout", {})
        self.ratio = float(ratio if ratio is not None else config.get("ratio", 0.20))
        # One look is what a holdout is for. The budget exists to be spendable once.
        self.budget = int(budget if budget is not None else config.get("budget", 1))
        self.ledger = ledger
        self.accesses: list[HoldoutAccess] = []
        self._split: HoldoutSplit | None = None

    # ------------------------------------------------------------------ split
    def split(self, observations: Sequence[ResearchObservation]) -> tuple[
            list[ResearchObservation], list[ResearchObservation]]:
        """Chronological split: the holdout is always the *most recent* tail."""
        rows = sorted((row for row in observations if row.resolved_at is not None),
                      key=lambda row: row.resolved_at)
        if not rows:
            return [], []
        cut = len(rows) - max(1, int(round(len(rows) * self.ratio)))
        cut = max(cut, 0)
        research, holdout = rows[:cut], rows[cut:]
        if research and holdout:
            self._split = HoldoutSplit(
                research_end=research[-1].resolved_at,
                holdout_start=holdout[0].resolved_at,
                holdout_end=holdout[-1].resolved_at,
                research_rows=len(research), holdout_rows=len(holdout))
        return research, holdout

    @property
    def last_split(self) -> HoldoutSplit | None:
        return self._split

    # ------------------------------------------------------------- protection
    @property
    def spent(self) -> bool:
        return len(self.accesses) >= self.budget

    @property
    def remaining(self) -> int:
        return max(self.budget - len(self.accesses), 0)

    def peek(self, holdout: Sequence[ResearchObservation], *, reason: str,
             now: datetime | None = None) -> list[ResearchObservation]:
        """Read the holdout. Refused once the budget is spent."""
        if not str(reason).strip():
            raise ValueError("reading the holdout requires a stated reason")
        if self.spent:
            raise HoldoutViolation(
                f"holdout budget of {self.budget} already spent; "
                f"previous reads: {[item.reason for item in self.accesses]}")
        access = HoldoutAccess(reason=str(reason), at=now or _utcnow(),
                               rows=len(holdout))
        self.accesses.append(access)
        if self.ledger is not None:
            self.ledger.record_holdout_use(access.reason)
        return list(holdout)

    def assert_untouched(self) -> None:
        """Guard for anything that must run before the holdout is opened."""
        if self.accesses:
            raise HoldoutViolation(
                f"holdout already read {len(self.accesses)} time(s): "
                f"{[item.reason for item in self.accesses]}")

    def contains_holdout(self, observations: Sequence[ResearchObservation]) -> bool:
        """True when a supposedly research-only set reaches into the holdout window."""
        if self._split is None:
            return False
        return any(row.resolved_at is not None
                   and row.resolved_at >= self._split.holdout_start
                   for row in observations)

    def report(self) -> dict[str, Any]:
        return {
            "ratio": self.ratio, "budget": self.budget,
            "usage": len(self.accesses), "remaining": self.remaining,
            "spent": self.spent,
            "accesses": [item.as_dict() for item in self.accesses],
            "split": self._split.as_dict() if self._split else None,
            "final_result_valid": len(self.accesses) <= 1,
            "warning": ("HOLDOUT_READ_MORE_THAN_ONCE" if len(self.accesses) > 1
                        else None),
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
