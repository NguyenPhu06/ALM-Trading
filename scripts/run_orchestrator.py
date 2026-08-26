"""Run the paper orchestration loop.

Execution is PAPER only: the loop's single execution call is PaperTradingService,
whose EnvironmentSafetyLock refuses any non-PAPER environment, and no broker
transport exists anywhere in the project.

    python -m scripts.run_orchestrator --once
    python -m scripts.run_orchestrator --symbol EURUSD --ticks 10 --interval 60
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database.repositories import PaperTradingRepository
from database.session import SessionLocal
from logging_config import configure_logging
from orchestration.runner import OrchestrationRunner
from paper import PaperTradingService


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the PAPER orchestration loop")
    parser.add_argument("--symbol", action="append", dest="symbols", default=None,
                        help="repeatable; defaults to phase_9.orchestration.symbols")
    parser.add_argument("--interval", type=float, default=None, help="seconds between ticks")
    parser.add_argument("--ticks", type=int, default=None, help="stop after N ticks")
    parser.add_argument("--once", action="store_true", help="run a single tick and exit")
    parser.add_argument("--enable", action="store_true",
                        help="run even when phase_9.orchestration.enabled is false")
    args = parser.parse_args()
    configure_logging()

    service = PaperTradingService()
    session = SessionLocal()
    try:
        service.restore(PaperTradingRepository(session))
    finally:
        session.close()
    service.start()

    runner = OrchestrationRunner(
        SessionLocal, service, symbols=args.symbols, interval_seconds=args.interval,
        enabled=True if args.enable or args.once else None,
    )
    if args.once:
        results = runner.tick()
    else:
        runner.run_forever(max_ticks=args.ticks)
        results = runner.last_results

    for result in results:
        print(f"{result.symbol} stage={result.stage} decision={result.decision} "
              f"model={result.model_status} quality={result.data_quality} "
              f"executed={'yes' if result.executed and result.executed.accepted else 'no'}")
        if result.reason_codes:
            print(f"  reasons: {', '.join(result.reason_codes)}")


if __name__ == "__main__":
    main()
