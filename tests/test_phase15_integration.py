"""The research lab end to end, and its persistence.

Runs the pipeline the way `scripts/run_research_lab.py` does: split the holdout,
run every study on the research portion, open the holdout once at the end.
"""
from datetime import timedelta

import pytest

from database.models import (
    ResearchExperimentRecord,
    ResearchFindingRecord,
    ResearchStrategyRecord,
)
from database.repositories.research import ResearchRepository
from research import (
    AblationStudy,
    ConflictEngine,
    DCAResearch,
    ErrorLab,
    ExitResearch,
    ExperimentLedger,
    ExperimentRunner,
    HoldoutGuard,
    LiquidityEventStudy,
    MatrixBuilder,
    NNValueTest,
    ResearchObservation,
    ResearchReporter,
    SignificanceTester,
    StrategyRegistry,
    catalogue,
    compare,
    strategy,
)
from research.models import require_forward_only
from research.registry import ApprovalToken, StrategyStatus
from tests.phase15_helpers import NOW, ablation_arms, observation, series, validated


def corpus(count=400):
    """A mixed corpus: two regimes, two sessions, some events, some DCA."""
    rows = []
    rows += series(count // 4, mean=0.0009, seed=1, regime="BULL", session="LONDON")
    rows += series(count // 4, mean=-0.0006, seed=2, start=1000, regime="BEAR",
                   session="ASIA", correct_rate=0.3, previous_regime="BULL")
    rows += series(count // 4, mean=0.0003, seed=3, start=2000, session="NEW_YORK",
                   liquidity_event="LIQUIDITY_SWEEP", dca_levels=1)
    rows += series(count // 4, mean=0.0001, seed=4, start=3000, confidence=None,
                   exit_kind="STRUCTURE_EXIT")
    return sorted(rows, key=lambda row: row.resolved_at)


# ------------------------------------------------------- the full pipeline
def test_the_lab_runs_every_study_over_one_corpus():
    rows = corpus()
    ledger = ExperimentLedger()
    guard = HoldoutGuard(ratio=0.2, budget=1, ledger=ledger)
    research, holdout = guard.split(rows)
    assert research and holdout

    runner = ExperimentRunner(minimum_samples=30, ledger=ledger)
    results = [runner.run(config, research) for config in catalogue()]
    ranking = compare(results)

    matrices = MatrixBuilder(minimum_samples=30)
    studies = {
        "strategy_comparison": ranking,
        "regime": matrices.regime(research).as_dict(),
        "session": matrices.session(research).as_dict(),
        "timeframe": matrices.timeframe(research).as_dict(),
        "transitions": matrices.transition_study(research),
        "dca": DCAResearch(minimum_samples=30).run(research).as_dict(),
        "exits": ExitResearch(minimum_samples=30).run(research).as_dict(),
        "events": LiquidityEventStudy(minimum_samples=30).run(research).as_dict(),
        "conflicts": ConflictEngine().study(research, minimum_samples=30),
        "errors": ErrorLab(minimum_samples=30).run(research),
        "nn_value": NNValueTest(minimum_samples=50).split(research).as_dict(),
    }
    assert all(payload for payload in studies.values())
    assert ledger.experiment_count == len(catalogue())

    # The holdout is opened last, exactly once.
    final = guard.peek(holdout, reason="final evaluation")
    assert len(final) == len(holdout)
    assert guard.report()["final_result_valid"] is True


def test_the_research_split_never_contains_holdout_rows():
    guard = HoldoutGuard(ratio=0.2)
    research, _ = guard.split(corpus())
    assert not guard.contains_holdout(research)


def test_every_study_reads_only_forward_evidence():
    rows = corpus(80)
    assert len(require_forward_only(rows)) == len(rows)
    assert all(str(row.evidence) == "FORWARD_OBSERVATION" for row in rows)


def test_the_matrices_agree_with_the_corpus_that_built_them():
    rows = corpus()
    matrices = MatrixBuilder(minimum_samples=30)
    regime = matrices.regime(rows)
    session = matrices.session(rows)
    assert "BULL" in regime.profitable
    assert "BEAR" in regime.losing
    assert "LONDON" in session.profitable
    assert "ASIA" in session.losing


def test_a_realistic_corpus_does_not_manufacture_an_edge():
    """With 8 configurations tried, nothing should survive the correction."""
    ledger = ExperimentLedger(alpha=0.05)
    runner = ExperimentRunner(minimum_samples=30, ledger=ledger)
    rows = corpus()
    for config in catalogue():
        result = runner.run(config, rows)
        ledger.record(result, p_value=0.20)
    report = ledger.report()
    assert report.hypotheses_tested > report.experiment_count
    assert report.survivors == ()


# ------------------------------------------------------------- persistence
def test_a_strategy_round_trips_through_the_repository(db_session):
    repository = ResearchRepository(db_session)
    registry = StrategyRegistry(repository=repository)
    registry.register(strategy("smc", "Liquidity + structure",
                               features=("liquidity", "market_structure"),
                               timeframes=("H1", "M15")))
    validated(registry, "smc:v1")
    registry.promote("smc:v1", ApprovalToken("nvphu", "integration"))

    row = repository.get_strategy("smc:v1")
    assert row.status == "CHAMPION"
    assert repository.champion_strategy().key == "smc:v1"
    assert repository.strategy_counts() == {"CHAMPION": 1}


def test_an_experiment_round_trips_and_upserts(db_session):
    repository = ResearchRepository(db_session)
    runner = ExperimentRunner(minimum_samples=30)
    result = runner.run(catalogue()[0], corpus(120))

    repository.save_experiment(result)
    repository.save_experiment(result)  # same content hash: one row, not two
    rows = db_session.query(ResearchExperimentRecord).all()
    assert len(rows) == 1
    assert rows[0].experiment_id == result.experiment_id
    assert rows[0].evidence == "FORWARD_OBSERVATION"
    assert repository.experiment_count() == 1


def test_the_best_experiment_is_the_best_reliable_one(db_session):
    repository = ResearchRepository(db_session)
    runner = ExperimentRunner(minimum_samples=30)
    strong = runner.run(catalogue()[0], series(200, mean=0.0012, seed=1))
    weak = runner.run(catalogue()[1], series(200, mean=0.0001, seed=2, start=1000))
    repository.save_experiment(strong)
    repository.save_experiment(weak)
    assert repository.best_experiment().experiment_id == strong.experiment_id


def test_an_unreliable_experiment_is_never_the_best(db_session):
    repository = ResearchRepository(db_session)
    runner = ExperimentRunner(minimum_samples=100)
    reliable = runner.run(catalogue()[0], series(200, mean=0.0004, seed=1))
    lucky = runner.run(catalogue()[1], series(5, mean=0.9, seed=2, start=1000))
    repository.save_experiment(reliable)
    repository.save_experiment(lucky)
    assert repository.best_experiment().experiment_id == reliable.experiment_id


def test_holdout_usage_is_visible_in_the_repository(db_session):
    repository = ResearchRepository(db_session)
    runner = ExperimentRunner(minimum_samples=30)
    result = runner.run(catalogue()[0], corpus(120))
    repository.save_experiment(result, used_holdout=True)
    assert repository.holdout_usage() == 1


def test_a_finding_is_recorded_with_its_verdict(db_session):
    repository = ResearchRepository(db_session)
    report = NNValueTest(minimum_samples=50).split(corpus())
    repository.save_finding(study="nn_value", subject="nn", verdict=str(report.verdict),
                            payload=report, sample_size=report.with_nn.sample_size,
                            significant=report.proven, reasons=report.reasons)
    row = db_session.query(ResearchFindingRecord).one()
    assert row.study == "nn_value"
    assert row.verdict == str(report.verdict)
    assert repository.latest_finding("nn_value").subject == "nn"


def test_no_research_table_holds_a_credential_or_a_binary():
    from database.base import Base

    for table in Base.metadata.sorted_tables:
        if not table.name.startswith("research_"):
            continue
        for column in table.columns:
            assert "blob" not in str(column.type).lower(), f"{table.name}.{column.name}"
            assert not any(token in column.name.lower()
                           for token in ("password", "secret", "credential", "token"))


# --------------------------------------------------------------- reporting
def test_the_lab_writes_a_full_report_set(tmp_path):
    rows = corpus()
    matrices = MatrixBuilder(minimum_samples=30)
    index = ResearchReporter(tmp_path).generate({
        "regime_analysis": matrices.regime(rows).as_dict(),
        "session_analysis": matrices.session(rows).as_dict(),
        "dca_analysis": DCAResearch(minimum_samples=30).run(rows).as_dict(),
        "ablation_analysis": AblationStudy(minimum_samples=30).run(
            ablation_arms(count=120)).as_dict(),
        "nn_value_analysis": NNValueTest(minimum_samples=50).split(rows).as_dict(),
    })
    assert len(index["reports"]) == 5
    for name in index["reports"]:
        assert (tmp_path / f"{name}.json").exists()
        assert (tmp_path / f"{name}.md").exists()


def test_the_written_markdown_is_readable(tmp_path):
    rows = corpus()
    ResearchReporter(tmp_path).generate({
        "regime_analysis": MatrixBuilder(minimum_samples=30).regime(rows).as_dict()})
    text = (tmp_path / "regime_analysis.md").read_text(encoding="utf-8")
    assert "# Regime Analysis" in text
    assert "| name |" in text
    assert "ORDERS SENT: 0" in text


def test_significance_over_the_whole_corpus_is_reported_honestly():
    rows = corpus()
    report = SignificanceTester(minimum_samples=100).absolute(
        [row.net_pnl for row in rows])
    assert report.sample_size == len(rows)
    assert report.verdict.value in {"SIGNIFICANT", "NOT_SIGNIFICANT", "UNSTABLE",
                                    "INSUFFICIENT_DATA"}
