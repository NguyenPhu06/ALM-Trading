"""Run the 24/7 forward observation driver (sections 1, 2, 27).

    python -m scripts.run_observation_driver
    python -m scripts.run_observation_driver --ticks 1 --dry-run
    python -m scripts.run_observation_driver --interval 900 --symbols EURUSD,GBPUSD

This process observes. It holds no execution client, sends no order and cannot
release the kill switch. It refuses to start unless observation mode is on and
every execution gate is closed — see `_refuse_unless_safe`.

SIGINT and SIGTERM request a graceful stop: the current tick finishes, then the
loop exits. Restarting is safe: cycle ids are deterministic, so a candle that was
already observed is skipped rather than duplicated.
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from datetime import datetime
from dataclasses import replace
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai.dataset.labels import LabelingEngine
from config.settings import get_settings
from database.models import MarketCandle
from database.repositories.alerts import AlertRepository
from database.repositories.forward import ForwardObservationRepository
from database.repositories.learning import LearningRepository
from database.repositories.observation import ObservationRepository
from database.session import SessionLocal
from execution.mt5.client import MT5ReadOnlyClient
from logging_config import configure_logging
from monitoring.alerts import (
    AlertEngine,
    AlertRepositoryNotificationProvider,
    AlertRouter,
)
from observation.cycle import ObservationCycle
from observation.driver import ALLOWED_INTERVALS, DriverConfig, ObservationDriver
from observation.ingestion import DatasetIngestor
from observation.outcome import ForwardOutcomeEngine

logger = logging.getLogger(__name__)


class UnsafeConfiguration(RuntimeError):
    """Raised when the driver would start with an execution gate open."""


def _refuse_unless_safe(settings) -> None:
    """The driver is observation-only. Refuse rather than observe with gates open."""
    problems = []
    if settings.live_trading_enabled:
        problems.append("LIVE_TRADING_ENABLED")
    if settings.demo_trading_enabled:
        problems.append("DEMO_TRADING_ENABLED")
    if settings.mt5_execution_enabled:
        problems.append("MT5_EXECUTION_ENABLED")
    if not settings.execution_kill_switch:
        problems.append("EXECUTION_KILL_SWITCH_RELEASED")
    if not settings.observation_mode:
        problems.append("OBSERVATION_MODE_OFF")
    if problems:
        raise UnsafeConfiguration(
            "refusing to start the observation driver: " + ", ".join(problems))


def candle_loader(session, timeframe: str):
    """Future candles for outcome resolution, read from the market data store."""
    def load(symbol: str, start: datetime, end: datetime) -> list[dict]:
        rows = (session.query(MarketCandle)
                .filter(MarketCandle.symbol == symbol.upper(),
                        MarketCandle.timeframe == timeframe.upper(),
                        MarketCandle.timestamp > start,
                        MarketCandle.timestamp <= end)
                .order_by(MarketCandle.timestamp).all())
        return [{"timestamp": row.timestamp, "open": float(row.open),
                 "high": float(row.high), "low": float(row.low),
                 "close": float(row.close)} for row in rows]
    return load


def build_driver(session, *, config: DriverConfig, dry_run: bool = False,
                 client=None) -> ObservationDriver:
    alerts = None
    if not dry_run:
        engine = AlertEngine(AlertRepositoryNotificationProvider(AlertRepository(session)))
        alerts = AlertRouter(engine)
    repository = None if dry_run else ForwardObservationRepository(session)
    cycle = ObservationCycle(session, client=client or MT5ReadOnlyClient(),
                             alerts=alerts, repository=ObservationRepository(session))
    ingestor = None if dry_run else DatasetIngestor(LearningRepository(session))
    return ObservationDriver(
        cycle=cycle, repository=repository, config=config, alerts=alerts,
        outcome_engine=ForwardOutcomeEngine(labeler=LabelingEngine()),
        candles=candle_loader(session, config.timeframe), ingestor=ingestor)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the forward observation driver")
    parser.add_argument("--interval", type=int, default=None,
                        choices=ALLOWED_INTERVALS,
                        help="seconds between ticks (default: phase_14.interval_seconds)")
    parser.add_argument("--symbols", default=None, help="comma separated, e.g. EURUSD,GBPUSD")
    parser.add_argument("--horizon", default=None, help="observation horizon, e.g. 1h")
    parser.add_argument("--ticks", type=int, default=None,
                        help="stop after this many ticks (default: run until stopped)")
    parser.add_argument("--dry-run", action="store_true",
                        help="run cycles without persisting observations or alerts")
    args = parser.parse_args()

    configure_logging()
    settings = get_settings()
    try:
        _refuse_unless_safe(settings)
    except UnsafeConfiguration as error:
        logger.error("%s", error)
        raise SystemExit(2) from error

    config = DriverConfig.from_settings(settings)
    overrides = {}
    if args.interval is not None:
        overrides["interval_seconds"] = args.interval
    if args.symbols:
        overrides["symbols"] = tuple(name.strip().upper()
                                     for name in args.symbols.split(",") if name.strip())
    if args.horizon:
        overrides["horizon"] = args.horizon
    if overrides:
        config = replace(config, **overrides)

    session = SessionLocal()
    try:
        driver = build_driver(session, config=config, dry_run=args.dry_run)

        def request_stop(signum, _frame):
            logger.info("signal %s received: finishing the current tick", signum)
            driver.stop(reason=f"SIGNAL_{signum}")

        for name in ("SIGINT", "SIGTERM"):
            handler = getattr(signal, name, None)
            if handler is not None:
                signal.signal(handler, request_stop)

        logger.info("observation driver starting: %s", json.dumps(config.as_dict()))
        ticks = driver.run_forever(max_ticks=args.ticks)
        summary = {
            "ticks": len(ticks),
            "executed": sum(len(tick.executed) for tick in ticks),
            "duplicates": sum(len(tick.duplicates) for tick in ticks),
            "failed": sum(len(tick.failures) for tick in ticks),
            "resolved": sum(len(tick.resolved) for tick in ticks),
            "state": str(driver.state), "orders_sent": 0,
        }
        print(json.dumps(summary, indent=2))
        print("OBSERVATION ONLY. ZERO ORDERS SENT. Training is a separate job: "
              "python -m scripts.train_forward_model")
    finally:
        session.close()


if __name__ == "__main__":
    main()
