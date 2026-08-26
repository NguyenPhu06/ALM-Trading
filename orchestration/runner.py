"""Drives OrchestrationCycle on an interval.

The runner owns the session lifetime (one session per tick), the tick-to-tick
memory, and the repository binding that makes paper state durable. It is disabled
by default: starting the API must never start trading activity on its own.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Sequence

from config.settings import load_yaml
from database.repositories import PaperTradingRepository
from orchestration.cycle import CycleResult, OrchestrationCycle
from paper.service import bound_repository

logger = logging.getLogger(__name__)


class OrchestrationRunner:
    def __init__(
        self,
        session_factory: Callable[[], Any],
        paper_service,
        *,
        symbols: Sequence[str] | None = None,
        interval_seconds: float | None = None,
        enabled: bool | None = None,
        inference: Any = None,
        cycle_options: dict[str, Any] | None = None,
    ):
        config = load_yaml().get("phase_9", {}).get("orchestration", {})
        self.session_factory = session_factory
        self.paper = paper_service
        self.symbols = tuple(symbols or config.get("symbols") or ("EURUSD",))
        self.interval_seconds = float(
            interval_seconds if interval_seconds is not None else config.get("interval_seconds", 60),
        )
        self.enabled = bool(config.get("enabled", False)) if enabled is None else bool(enabled)
        self.inference = inference
        self.cycle_options = dict(cycle_options or {})
        self.memory: dict[str, Any] = {}
        self.last_results: tuple[CycleResult, ...] = ()
        self._stop = threading.Event()

    def tick(self) -> tuple[CycleResult, ...]:
        """One pass over every configured symbol. A failing symbol never stops the rest."""
        results: list[CycleResult] = []
        for symbol in self.symbols:
            session = self.session_factory()
            try:
                with bound_repository(self.paper, PaperTradingRepository(session)):
                    cycle = OrchestrationCycle(
                        session, paper_service=self.paper, memory=self.memory,
                        inference=self.inference, **self.cycle_options,
                    )
                    results.append(cycle.run(symbol))
            except Exception:
                logger.exception("orchestration tick failed for %s", symbol)
            finally:
                session.close()
        self.last_results = tuple(results)
        return self.last_results

    def run_forever(self, *, max_ticks: int | None = None) -> int:
        if not self.enabled:
            logger.info("orchestration loop is disabled by configuration; not starting")
            return 0
        self._stop.clear()
        completed = 0
        while not self._stop.is_set() and (max_ticks is None or completed < max_ticks):
            self.tick()
            completed += 1
            if max_ticks is not None and completed >= max_ticks:
                break
            self._stop.wait(self.interval_seconds)
        return completed

    def stop(self) -> None:
        self._stop.set()

    def start_background(self) -> threading.Thread | None:
        if not self.enabled:
            logger.info("orchestration loop is disabled by configuration; not starting")
            return None
        thread = threading.Thread(target=self.run_forever, name="orchestration", daemon=True)
        thread.start()
        return thread
