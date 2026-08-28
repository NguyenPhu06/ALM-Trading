"""Forward-only evaluation (section 24).

    BACKTEST < PAPER < FORWARD_OBSERVATION < DEMO_EXECUTION < LIVE_EXECUTION

Forward observation is the primary evaluation source. A backtest may never stand
in for it, and nothing in this repository produces DEMO_EXECUTION or
LIVE_EXECUTION evidence — those names exist so a future phase has a word for them.
"""
import pathlib

import pytest

from ai.edge.evidence import (
    EVIDENCE_STRENGTH,
    PRIMARY_EVIDENCE,
    RETROSPECTIVE,
    EvidenceRefused,
    EvidenceSource,
    require_forward,
    stronger_than,
)
from ai.performance.rolling import RollingPerformance
from tests.phase14_helpers import NOW, performance_entries


# ------------------------------------------------------ the five sources
def test_all_five_sources_are_named():
    assert {str(item) for item in EvidenceSource} == {
        "BACKTEST", "PAPER", "FORWARD_OBSERVATION", "DEMO_EXECUTION", "LIVE_EXECUTION"}


def test_forward_observation_is_the_primary_source():
    assert PRIMARY_EVIDENCE is EvidenceSource.FORWARD_OBSERVATION


def test_the_sources_are_ordered_weakest_to_strongest():
    order = sorted(EVIDENCE_STRENGTH, key=EVIDENCE_STRENGTH.get)
    assert [str(item) for item in order] == [
        "BACKTEST", "PAPER", "FORWARD_OBSERVATION", "DEMO_EXECUTION", "LIVE_EXECUTION"]


def test_backtest_and_paper_are_retrospective():
    assert RETROSPECTIVE == {EvidenceSource.BACKTEST, EvidenceSource.PAPER}


def test_forward_observation_beats_both_retrospective_sources():
    assert stronger_than(EvidenceSource.FORWARD_OBSERVATION, EvidenceSource.BACKTEST)
    assert stronger_than(EvidenceSource.FORWARD_OBSERVATION, EvidenceSource.PAPER)


def test_forward_observation_is_weaker_than_real_execution():
    assert stronger_than(EvidenceSource.DEMO_EXECUTION,
                         EvidenceSource.FORWARD_OBSERVATION)
    assert stronger_than(EvidenceSource.LIVE_EXECUTION, EvidenceSource.DEMO_EXECUTION)


# ------------------------------------------------------------- the gate
def test_forward_evidence_passes_the_gate():
    assert require_forward(EvidenceSource.FORWARD_OBSERVATION) is PRIMARY_EVIDENCE


def test_forward_evidence_can_be_named_by_string():
    assert require_forward("FORWARD_OBSERVATION") is PRIMARY_EVIDENCE


@pytest.mark.parametrize("source", ["BACKTEST", "PAPER", "DEMO_EXECUTION",
                                    "LIVE_EXECUTION"])
def test_every_other_source_is_refused_by_name(source):
    with pytest.raises(EvidenceRefused, match=source):
        require_forward(source)


def test_an_unknown_source_is_rejected():
    with pytest.raises(ValueError):
        require_forward("VIBES")


# ---------------------------------------------- no backtest in the pipeline
def test_no_phase_14_module_imports_a_backtester():
    modules = ("observation/driver.py", "observation/outcome.py",
               "observation/ingestion.py", "ai/edge/edge_detector.py",
               "ai/performance/rolling.py", "ai/performance/segments.py")
    for module in modules:
        source = pathlib.Path(module).read_text(encoding="utf-8")
        for token in ("backtest", "Backtest", "BACKTEST"):
            if token in source:
                # The only permitted mention is naming it as an excluded source.
                assert "EvidenceSource" in source or "not a backtest" in source, module


def test_nothing_produces_demo_or_live_execution_evidence():
    """Those names exist for a future phase; no code path emits them today."""
    offenders = []
    for path in pathlib.Path(".").glob("[!.]*/**/*.py"):
        if "test" in path.parts[0] or path.parts[0] in {"node_modules", "frontend"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in ("EvidenceSource.DEMO_EXECUTION", "EvidenceSource.LIVE_EXECUTION"):
            if token in text and "evidence.py" not in path.as_posix():
                offenders.append(f"{path.as_posix()}:{token}")
    assert offenders == [], offenders


# -------------------------------------------------- rolling reports the source
def test_rolling_performance_is_computed_from_forward_entries():
    summary = RollingPerformance().summary(performance_entries(40, now=NOW), now=NOW)
    assert summary["total_samples"] == 40
    assert summary["windows"]["7d"]["samples"] == 40


def test_the_outcome_record_defaults_to_forward_observation(db_session):
    from database.repositories.forward import ForwardObservationRepository
    from tests.phase14_helpers import observation, outcome

    repository = ForwardObservationRepository(db_session)
    row = repository.save_outcome(observation(1), outcome(1))
    assert row.evidence == "FORWARD_OBSERVATION"


def test_the_edge_record_defaults_to_forward_observation(db_session):
    from ai.edge import EdgeDetector
    from database.repositories.forward import ForwardObservationRepository
    from tests.phase14_helpers import BASELINES, entries

    report = EdgeDetector().evaluate(entries(120, net=0.0004), baselines=BASELINES)
    row = ForwardObservationRepository(db_session).save_edge(report, symbol="EURUSD")
    assert row.evidence == "FORWARD_OBSERVATION"
