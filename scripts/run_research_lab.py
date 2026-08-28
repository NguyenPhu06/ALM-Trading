"""Run the AI research lab and write its reports (sections 24, 28).

    python -m scripts.run_research_lab
    python -m scripts.run_research_lab --days 90 --output reports/research

This job reads recorded forward observations, runs every study, and writes JSON
plus Markdown to `reports/research/`. It holds no execution client, sends no
order and changes no setting.

The holdout is read **once**, at the end, for the final evaluation only. Every
read is counted and appears in the multiple-testing report.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.settings import get_settings
from database.repositories.forward import ForwardObservationRepository
from database.repositories.research import ResearchRepository
from database.session import SessionLocal
from logging_config import configure_logging
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
    SelectionMethod,
    SignalWeightResearch,
    SignificanceTester,
    catalogue,
    compare,
)

logger = logging.getLogger(__name__)


class UnsafeConfiguration(RuntimeError):
    """Raised when research would run with an execution gate open."""


def _refuse_unless_safe(settings) -> None:
    """Research is read-only, but it refuses to run beside an open gate."""
    problems = []
    if settings.live_trading_enabled:
        problems.append("LIVE_TRADING_ENABLED")
    if settings.demo_trading_enabled:
        problems.append("DEMO_TRADING_ENABLED")
    if settings.mt5_execution_enabled:
        problems.append("MT5_EXECUTION_ENABLED")
    if not settings.execution_kill_switch:
        problems.append("EXECUTION_KILL_SWITCH_RELEASED")
    if problems:
        raise UnsafeConfiguration(
            "refusing to run research: " + ", ".join(problems))


def load_observations(session, *, days: int) -> list[ResearchObservation]:
    forward = ForwardObservationRepository(session)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[ResearchObservation] = []
    for row in forward.outcomes_since(since, limit=50000):
        observation = forward.get_observation(row.observation_id)
        overrides = {}
        if observation is not None:
            overrides["confidence"] = observation.nn_confidence
            overrides["strategy_id"] = observation.strategy
        rows.append(ResearchObservation.from_row(row, **overrides))
    return rows


def run_studies(observations: list[ResearchObservation], *,
                repository: ResearchRepository | None = None) -> dict[str, dict]:
    """Every study, over the research split. The holdout stays closed until the end."""
    ledger = ExperimentLedger(alpha=0.05, selection_method=SelectionMethod.EXPLORATORY)
    guard = HoldoutGuard(ledger=ledger)
    research, holdout = guard.split(observations)

    matrices = MatrixBuilder()
    runner = ExperimentRunner(ledger=ledger)
    tester = SignificanceTester()

    configs = catalogue()
    results = [runner.run(config, research, strategy_version="v1") for config in configs]
    if repository is not None:
        for result in results:
            repository.save_experiment(result)

    with_nn = [row for row in research if row.confidence is not None]
    without_nn = [row for row in research if row.confidence is None]

    reports = {
        "strategy_comparison": compare(results),
        "regime_analysis": matrices.regime(research).as_dict(),
        "session_analysis": matrices.session(research).as_dict(),
        "timeframe_analysis": matrices.timeframe(research).as_dict(),
        "regime_transitions": matrices.transition_study(research),
        "nn_value_analysis": NNValueTest().run(without_nn=without_nn,
                                               with_nn=with_nn).as_dict(),
        "dca_analysis": DCAResearch().run(research).as_dict(),
        "time_exit_analysis": ExitResearch().run(research).as_dict(),
        "liquidity_event_analysis": LiquidityEventStudy().run(research).as_dict(),
        "signal_conflicts": ConflictEngine().study(research),
        "signal_weights": SignalWeightResearch().run(research).as_dict(),
        "error_lab": ErrorLab().run(research),
        "significance": tester.absolute([row.net_pnl for row in research]).as_dict(),
    }

    # The holdout is opened last, once, for the final number only.
    if holdout:
        final = guard.peek(holdout, reason="final evaluation")
        reports["holdout_final_evaluation"] = {
            "observations": len(final),
            "significance": tester.absolute([row.net_pnl for row in final]).as_dict(),
            **guard.report(),
        }
    reports["multiple_testing"] = ledger.as_dict()
    reports["holdout_protection"] = guard.report()
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AI research lab")
    parser.add_argument("--days", type=int, default=180,
                        help="observation lookback window")
    parser.add_argument("--output", default=None, help="report directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="run the studies without writing reports or database rows")
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()
    try:
        _refuse_unless_safe(settings)
    except UnsafeConfiguration as error:
        logger.error("%s", error)
        raise SystemExit(2) from error

    session = SessionLocal()
    try:
        repository = None if args.dry_run else ResearchRepository(session)
        observations = load_observations(session, days=args.days)
        logger.info("loaded %d forward observations", len(observations))
        if not observations:
            print(json.dumps({"observations": 0,
                              "result": "NO_FORWARD_OBSERVATIONS",
                              "note": "Research needs recorded forward outcomes. "
                                      "Run the observation driver first.",
                              "orders_sent": 0}, indent=2))
            return

        reports = run_studies(observations, repository=repository)
        if args.dry_run:
            print(json.dumps({"observations": len(observations),
                              "studies": sorted(reports), "written": False,
                              "orders_sent": 0}, indent=2))
            return

        directory = args.output or load_reports_path()
        index = ResearchReporter(directory).generate(reports)
        print(json.dumps({"observations": len(observations),
                          "reports": sorted(index["reports"]),
                          "directory": str(directory), "orders_sent": 0}, indent=2))
        print("RESEARCH ONLY. ZERO ORDERS SENT. Promotion requires human approval.")
    finally:
        session.close()


def load_reports_path() -> str:
    from config.settings import load_yaml

    return str(load_yaml().get("phase_15", {}).get("reports_path", "reports/research"))


if __name__ == "__main__":
    main()
