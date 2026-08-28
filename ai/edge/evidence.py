"""Evidence provenance (section 24).

Not all evidence is equal. A backtest is a hypothesis about the past; a forward
observation is a prediction that was recorded before the outcome existed. The
system must never let the first stand in for the second, so every performance
figure carries the source that produced it.

`FORWARD_OBSERVATION` is the primary evaluation source. `DEMO_EXECUTION` and
`LIVE_EXECUTION` exist in this vocabulary so that a future phase has a name for
them; no code path in this repository produces either.
"""
from __future__ import annotations

from enum import StrEnum


class EvidenceSource(StrEnum):
    BACKTEST = "BACKTEST"
    PAPER = "PAPER"
    FORWARD_OBSERVATION = "FORWARD_OBSERVATION"
    DEMO_EXECUTION = "DEMO_EXECUTION"
    LIVE_EXECUTION = "LIVE_EXECUTION"


# Ordered weakest to strongest as evidence that a strategy works.
EVIDENCE_STRENGTH: dict[EvidenceSource, int] = {
    EvidenceSource.BACKTEST: 0,
    EvidenceSource.PAPER: 1,
    EvidenceSource.FORWARD_OBSERVATION: 2,
    EvidenceSource.DEMO_EXECUTION: 3,
    EvidenceSource.LIVE_EXECUTION: 4,
}

# The only source this phase accepts as primary evidence of an edge.
PRIMARY_EVIDENCE = EvidenceSource.FORWARD_OBSERVATION

# Sources that are simulations of the past rather than recorded predictions.
RETROSPECTIVE = frozenset({EvidenceSource.BACKTEST, EvidenceSource.PAPER})


class EvidenceRefused(ValueError):
    """Raised when retrospective evidence is offered where forward evidence is required."""


def require_forward(source: EvidenceSource | str) -> EvidenceSource:
    """Gate for anything that claims an edge. Backtests are refused by name."""
    value = EvidenceSource(source)
    if value is not PRIMARY_EVIDENCE:
        raise EvidenceRefused(
            f"{value} cannot substitute for {PRIMARY_EVIDENCE}: "
            "edge claims require forward observation data")
    return value


def stronger_than(left: EvidenceSource | str, right: EvidenceSource | str) -> bool:
    return EVIDENCE_STRENGTH[EvidenceSource(left)] > EVIDENCE_STRENGTH[EvidenceSource(right)]
