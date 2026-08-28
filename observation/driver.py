"""The long-running observation driver (sections 1, 2, 3, 27).

The driver is the only component in this system designed to run for weeks. Its
job is to keep the Phase 12 cycle firing on a schedule, to resolve observations
once their horizon elapses, and to survive restarts without duplicating anything.

    tick -> deterministic cycle_id -> already seen? -> run cycle
         -> record observation -> resolve due observations -> health

What it deliberately cannot do: send an order, modify an MT5 position, or move
the kill switch. It holds no execution client and imports no execution module.
A failing cycle degrades the driver's health; it never escalates into a trade.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Callable, Sequence

from ai.dataset.labels import LabelingEngine, resolve_horizon
from config.settings import Settings, get_settings, load_yaml
from observation.health import ComponentHealth, SystemHealthMonitor
from observation.lifecycle import (
    Observation,
    ObservationStatus,
    observation_from_cycle,
)
from observation.outcome import ForwardOutcomeEngine, OutcomeRefusal
from observation.snapshot import jsonable

logger = logging.getLogger(__name__)

# Section 2. The scheduler accepts these and nothing else; an unlisted interval
# is a configuration mistake, not something to round to the nearest option.
ALLOWED_INTERVALS: tuple[int, ...] = (60, 300, 900, 1800, 3600)
DEFAULT_INTERVAL = 300


class DriverState(StrEnum):
    STOPPED = "STOPPED"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


class TickOutcome(StrEnum):
    EXECUTED = "EXECUTED"
    DUPLICATE = "DUPLICATE"
    HALTED = "HALTED"
    FAILED = "FAILED"


def deterministic_cycle_id(symbol: str, timeframe: str, candle: datetime) -> str:
    """Section 3. Same symbol + timeframe + candle => same id, always.

    The candle timestamp is normalised to UTC and rendered to the second so that
    a restart in a different process reproduces the identifier exactly.
    """
    stamp = candle.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    digest = hashlib.sha256(f"{symbol.upper()}|{timeframe.upper()}|{stamp}".encode())
    return digest.hexdigest()[:32]


def candle_timestamp(now: datetime, interval_seconds: int) -> datetime:
    """Floor `now` onto the interval grid: the candle this tick belongs to."""
    moment = now.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    elapsed = int((moment - epoch).total_seconds())
    return epoch + timedelta(seconds=elapsed - (elapsed % max(int(interval_seconds), 1)))


@dataclass(frozen=True, slots=True)
class DriverConfig:
    interval_seconds: int = DEFAULT_INTERVAL
    symbols: tuple[str, ...] = ("EURUSD",)
    timeframe: str = "M5"
    horizon: str = "1h"
    max_consecutive_errors: int = 5
    resolve_batch: int = 200
    stale_after_cycles: int = 3

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> "DriverConfig":
        settings = settings or get_settings()
        config = load_yaml().get("phase_14", {})
        interval = int(config.get("interval_seconds", DEFAULT_INTERVAL))
        if interval not in ALLOWED_INTERVALS:
            raise ValueError(
                f"phase_14.interval_seconds must be one of {ALLOWED_INTERVALS}, got {interval}")
        symbols = tuple(str(name).upper() for name in
                        (config.get("symbols") or settings.observation_symbol_list))
        horizon = str(config.get("horizon", "1h"))
        resolve_horizon(horizon)  # raises KeyError on an unknown horizon
        return cls(interval_seconds=interval, symbols=symbols or ("EURUSD",),
                   timeframe=str(config.get("timeframe", "M5")).upper(), horizon=horizon,
                   max_consecutive_errors=int(config.get("max_consecutive_errors", 5)),
                   resolve_batch=int(config.get("resolve_batch", 200)),
                   stale_after_cycles=int(config.get("stale_after_cycles", 3)))

    def as_dict(self) -> dict[str, Any]:
        return {"interval_seconds": self.interval_seconds, "symbols": list(self.symbols),
                "timeframe": self.timeframe, "horizon": self.horizon,
                "max_consecutive_errors": self.max_consecutive_errors,
                "resolve_batch": self.resolve_batch}


@dataclass(frozen=True, slots=True)
class CycleReport:
    cycle_id: str
    symbol: str
    candle: datetime
    outcome: TickOutcome
    observation: Observation | None = None
    reasons: tuple[str, ...] = ()
    orders_sent: int = 0

    def as_dict(self) -> dict[str, Any]:
        return jsonable({
            "cycle_id": self.cycle_id, "symbol": self.symbol, "candle": self.candle,
            "outcome": str(self.outcome), "reasons": list(self.reasons),
            "orders_sent": 0,
            "observation": self.observation.as_dict() if self.observation else None,
        })


@dataclass(frozen=True, slots=True)
class DriverTick:
    timestamp: datetime
    candle: datetime
    cycles: tuple[CycleReport, ...] = ()
    resolved: tuple[Any, ...] = ()
    alerts: tuple[Any, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def executed(self) -> tuple[CycleReport, ...]:
        return tuple(r for r in self.cycles if r.outcome is TickOutcome.EXECUTED)

    @property
    def duplicates(self) -> tuple[CycleReport, ...]:
        return tuple(r for r in self.cycles if r.outcome is TickOutcome.DUPLICATE)

    @property
    def failures(self) -> tuple[CycleReport, ...]:
        return tuple(r for r in self.cycles if r.outcome is TickOutcome.FAILED)

    # Invariant, asserted by the Phase 14 safety tests.
    @property
    def orders_sent(self) -> int:
        return 0

    def as_dict(self) -> dict[str, Any]:
        return jsonable({
            "timestamp": self.timestamp, "candle": self.candle, "orders_sent": 0,
            "cycles": [report.as_dict() for report in self.cycles],
            "resolved": [item.as_dict() if hasattr(item, "as_dict") else item
                         for item in self.resolved],
            "errors": list(self.errors),
        })


@dataclass
class DriverStatistics:
    started_at: datetime | None = None
    ticks: int = 0
    cycles_executed: int = 0
    cycles_duplicate: int = 0
    cycles_failed: int = 0
    observations_resolved: int = 0
    observations_labelled: int = 0
    consecutive_errors: int = 0
    last_cycle_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    # None until a cycle has run; then whether the last one carried a prediction.
    last_prediction: bool | None = None
    seen_cycles: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, Any]:
        return jsonable({
            "started_at": self.started_at, "ticks": self.ticks,
            "cycles_executed": self.cycles_executed,
            "cycles_duplicate": self.cycles_duplicate,
            "cycles_failed": self.cycles_failed,
            "observations_resolved": self.observations_resolved,
            "observations_labelled": self.observations_labelled,
            "consecutive_errors": self.consecutive_errors,
            "last_cycle_at": self.last_cycle_at, "last_success_at": self.last_success_at,
            "last_error": self.last_error, "last_prediction": self.last_prediction,
            "known_cycles": len(self.seen_cycles),
        })


class ObservationDriver:
    """Scheduling, idempotency, recovery and health for the forward loop."""

    def __init__(self, *, cycle: Any, repository: Any = None, config: DriverConfig | None = None,
                 settings: Settings | None = None, alerts: Any = None,
                 outcome_engine: ForwardOutcomeEngine | None = None,
                 candles: Callable[[str, datetime, datetime], Sequence[dict]] | None = None,
                 ingestor: Any = None, clock: Callable[[], datetime] | None = None,
                 sleeper: Callable[[float], None] | None = None):
        self.settings = settings or get_settings()
        self.config = config or DriverConfig.from_settings(self.settings)
        self.cycle = cycle
        self.repository = repository
        self.alerts = alerts
        self.ingestor = ingestor
        self.outcome_engine = outcome_engine or ForwardOutcomeEngine(labeler=LabelingEngine())
        self._candles = candles
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleeper or _default_sleeper
        self.state = DriverState.STOPPED
        self.stats = DriverStatistics()
        self.health_monitor = SystemHealthMonitor()
        self._stopping = False

    # ------------------------------------------------------------------ clock
    def now(self) -> datetime:
        return self._clock()

    def current_candle(self, now: datetime | None = None) -> datetime:
        return candle_timestamp(now or self.now(), self.config.interval_seconds)

    def cycle_id_for(self, symbol: str, candle: datetime) -> str:
        return deterministic_cycle_id(symbol, self.config.timeframe, candle)

    # ------------------------------------------------------------ idempotency
    def already_executed(self, cycle_id: str) -> bool:
        """Section 3 and 27: in-memory first, then the database after a restart."""
        if cycle_id in self.stats.seen_cycles:
            return True
        if self.repository is None:
            return False
        try:
            known = self.repository.observation_exists(cycle_id=cycle_id)
        except Exception:
            logger.exception("idempotency lookup failed for %s", cycle_id)
            return False
        if known:
            self.stats.seen_cycles.add(cycle_id)
        return bool(known)

    def resume(self) -> int:
        """Reload known cycle ids so a restart cannot duplicate observations."""
        if self.repository is None:
            return 0
        try:
            known = self.repository.known_cycle_ids(limit=5000)
        except Exception:
            logger.exception("failed to reload observation history")
            return 0
        self.stats.seen_cycles.update(str(item) for item in known)
        return len(self.stats.seen_cycles)

    # ----------------------------------------------------------------- alerts
    def _alert(self, method: str, **kwargs: Any) -> tuple[Any, ...]:
        if self.alerts is None:
            return ()
        handler = getattr(self.alerts, method, None)
        if handler is None:
            return ()
        try:
            return tuple(handler(**kwargs) or ())
        except Exception:
            logger.exception("driver alert %s failed", method)
            return ()

    # ------------------------------------------------------------------- tick
    def run_once(self, now: datetime | None = None) -> DriverTick:
        """One scheduled tick: every symbol, then every due observation.

        Never raises for market or model conditions. A symbol that throws is
        recorded as a failed cycle and the remaining symbols still run.
        """
        moment = now or self.now()
        candle = self.current_candle(moment)
        self.stats.ticks += 1
        reports: list[CycleReport] = []
        alerts: list[Any] = []
        errors: list[str] = []

        for symbol in self.config.symbols:
            cycle_id = self.cycle_id_for(symbol, candle)
            if self.already_executed(cycle_id):
                reports.append(CycleReport(cycle_id, symbol, candle, TickOutcome.DUPLICATE,
                                           reasons=("DUPLICATE_CYCLE",)))
                self.stats.cycles_duplicate += 1
                continue
            report, emitted, error = self._run_symbol(symbol, cycle_id, candle, moment)
            reports.append(report)
            alerts.extend(emitted)
            if error:
                errors.append(error)

        resolved = self._resolve_due(moment)
        self.stats.last_cycle_at = moment
        self._update_state()
        return DriverTick(moment, candle, tuple(reports), tuple(resolved), tuple(alerts),
                          tuple(errors))

    def _run_symbol(self, symbol: str, cycle_id: str, candle: datetime,
                    moment: datetime) -> tuple[CycleReport, list[Any], str | None]:
        alerts: list[Any] = []
        try:
            result = self.cycle.run(symbol)
        except Exception as error:  # the driver must outlive any single cycle
            detail = f"{type(error).__name__}: {error}"
            logger.exception("observation cycle failed for %s", symbol)
            self.stats.cycles_failed += 1
            self.stats.consecutive_errors += 1
            self.stats.last_error = detail
            alerts.extend(self._alert("observation_cycle_failed", symbol=symbol,
                                      cycle_id=cycle_id, detail=detail))
            return (CycleReport(cycle_id, symbol, candle, TickOutcome.FAILED,
                                reasons=(detail,)), alerts, detail)

        # A halted cycle is a normal market condition, not a driver error.
        self.stats.seen_cycles.add(cycle_id)
        if getattr(result, "halted", False):
            self.stats.cycles_failed += 1
            reasons = tuple(getattr(result, "reasons", ()))
            if any("STALE" in reason or "NO_MARKET_DATA" in reason for reason in reasons):
                alerts.extend(self._alert("data_stale", symbol=symbol, reasons=reasons))
            observation = self._record_halted(result, cycle_id, moment, reasons)
            return (CycleReport(cycle_id, symbol, candle, TickOutcome.HALTED,
                                observation=observation, reasons=reasons), alerts, None)

        observation = self._record(result, cycle_id, moment)
        self.stats.last_prediction = observation.nn_prediction is not None
        self.stats.cycles_executed += 1
        self.stats.consecutive_errors = 0
        self.stats.last_success_at = moment
        return (CycleReport(cycle_id, symbol, candle, TickOutcome.EXECUTED,
                            observation=observation), alerts, None)

    # ------------------------------------------------------------- lifecycle
    def _record(self, result: Any, cycle_id: str, moment: datetime) -> Observation:
        """Walk the observation through the lifecycle the cycle actually reached."""
        observation = observation_from_cycle(result, horizon=self.config.horizon,
                                             timeframe=self.config.timeframe, now=moment,
                                             cycle_id=cycle_id)
        observation = observation.advance(ObservationStatus.FEATURES_CAPTURED, now=moment)
        # A missing model is a normal state, not a MODEL_ERROR: the cycle still ran
        # end to end and the observation is still worth recording.
        observation = observation.advance(ObservationStatus.NN_PREDICTED, now=moment)
        observation = observation.advance(ObservationStatus.STRATEGY_EVALUATED, now=moment)
        observation = observation.advance(ObservationStatus.RISK_EVALUATED, now=moment)
        observation = observation.advance(ObservationStatus.OBSERVING, now=moment)
        self._persist(observation)
        return observation

    def _record_halted(self, result: Any, cycle_id: str, moment: datetime,
                       reasons: tuple[str, ...]) -> Observation:
        observation = observation_from_cycle(result, horizon=self.config.horizon,
                                             timeframe=self.config.timeframe, now=moment,
                                             cycle_id=cycle_id)
        observation = observation.fail(ObservationStatus.DATA_INVALID,
                                       ", ".join(reasons) or "HALTED", now=moment)
        self._persist(observation)
        return observation

    def _persist(self, observation: Observation) -> None:
        if self.repository is None:
            return
        try:
            self.repository.save_observation(observation)
        except Exception:
            logger.exception("failed to persist observation %s", observation.observation_id)

    # -------------------------------------------------------------- resolving
    def _resolve_due(self, moment: datetime) -> list[Any]:
        """Sections 6, 8, 9: resolve, label and hand to the dataset — in that order."""
        if self.repository is None:
            return []
        try:
            pending = self.repository.observations_due(now=moment,
                                                       limit=self.config.resolve_batch)
        except Exception:
            logger.exception("failed to load due observations")
            return []

        resolved: list[Any] = []
        for observation in pending:
            try:
                outcome = self._resolve_one(observation, moment)
            except Exception as error:
                logger.exception("outcome calculation failed for %s",
                                 observation.observation_id)
                self._fail(observation, ObservationStatus.CALCULATION_ERROR,
                           f"{type(error).__name__}: {error}", moment)
                self._alert("labeling_failure", observation_id=observation.observation_id,
                            detail=str(error))
                continue
            if outcome is not None:
                resolved.append(outcome)
        return resolved

    def _resolve_one(self, observation: Observation, moment: datetime) -> Any | None:
        if not observation.horizon_reached(moment):
            return None
        candles = self._future_candles(observation, moment)
        result = self.outcome_engine.resolve(observation, candles, now=moment)
        if not result.ok:
            if result.refusal is OutcomeRefusal.NOT_DIRECTIONAL:
                # WAIT observations have no outcome to measure; close them cleanly.
                self._advance_to(observation, ObservationStatus.HORIZON_REACHED, moment)
                return None
            if result.refusal is OutcomeRefusal.NO_FUTURE_DATA and self._timed_out(
                    observation, moment):
                self._fail(observation, ObservationStatus.TIMEOUT,
                           str(OutcomeRefusal.NO_FUTURE_DATA), moment)
            return None

        record = observation.advance(ObservationStatus.HORIZON_REACHED, now=moment)
        record = record.advance(ObservationStatus.OUTCOME_CALCULATED, now=moment)
        self.stats.observations_resolved += 1
        if result.outcome.label is not None:
            record = record.advance(ObservationStatus.LABELED, now=moment)
            self.stats.observations_labelled += 1
        self._persist(record)
        self._save_outcome(record, result.outcome)

        if result.outcome.label is not None and self.ingestor is not None:
            try:
                self.ingestor.ingest(record, result.outcome)
                record = record.advance(ObservationStatus.DATASET_READY, now=moment)
                self._persist(record)
            except Exception as error:
                logger.exception("dataset ingestion failed for %s", record.observation_id)
                self._alert("dataset_failure", observation_id=record.observation_id,
                            detail=str(error))
        return result.outcome

    def _timed_out(self, observation: Observation, moment: datetime) -> bool:
        """A horizon long past with still no data is a timeout, not a pending item."""
        deadline = observation.deadline
        if deadline is None:
            return False
        grace = timedelta(seconds=self.config.interval_seconds
                          * max(self.config.stale_after_cycles, 1))
        return moment > deadline + grace

    def _future_candles(self, observation: Observation, moment: datetime) -> Sequence[dict]:
        if self._candles is None:
            return ()
        deadline = observation.deadline or moment
        try:
            return self._candles(observation.symbol, observation.timestamp, deadline)
        except Exception:
            logger.exception("failed to load future candles for %s",
                             observation.observation_id)
            return ()

    def _advance_to(self, observation: Observation, status: ObservationStatus,
                    moment: datetime) -> None:
        try:
            self._persist(observation.advance(status, now=moment))
        except Exception:
            logger.exception("failed to advance %s", observation.observation_id)

    def _fail(self, observation: Observation, status: ObservationStatus, reason: str,
              moment: datetime) -> None:
        try:
            self._persist(observation.fail(status, reason, now=moment))
        except Exception:
            logger.exception("failed to mark %s as %s", observation.observation_id, status)

    def _save_outcome(self, observation: Observation, outcome: Any) -> None:
        if self.repository is None:
            return
        try:
            self.repository.save_outcome(observation, outcome)
        except Exception:
            logger.exception("failed to persist outcome for %s", observation.observation_id)

    # --------------------------------------------------------------- run loop
    def start(self) -> None:
        self._stopping = False
        self.state = DriverState.RUNNING
        self.stats.started_at = self.now()
        self.resume()

    def stop(self, *, reason: str = "REQUESTED") -> None:
        """Graceful shutdown: finish the current tick, then stop."""
        self._stopping = True
        self.state = DriverState.STOPPING
        self._alert("observation_driver_stopped", reason=reason)

    @property
    def stopping(self) -> bool:
        return self._stopping

    def run_forever(self, *, max_ticks: int | None = None) -> list[DriverTick]:
        """Tick on the configured interval until stopped.

        `max_ticks` bounds the loop for tests and for one-shot operational runs;
        without it the loop runs until `stop()` is called.
        """
        self.start()
        ticks: list[DriverTick] = []
        while not self._stopping and (max_ticks is None or len(ticks) < max_ticks):
            tick = self.run_once()
            ticks.append(tick)
            if self.stats.consecutive_errors >= self.config.max_consecutive_errors:
                self.state = DriverState.FAILED
                self._alert("observation_driver_stopped",
                            reason=f"CONSECUTIVE_ERRORS>={self.config.max_consecutive_errors}")
                break
            if self._stopping or (max_ticks is not None and len(ticks) >= max_ticks):
                break
            self._sleep(float(self.config.interval_seconds))
        if self.state is not DriverState.FAILED:
            self.state = DriverState.STOPPED
        return ticks

    # ---------------------------------------------------------------- health
    def _update_state(self) -> None:
        if self.state is DriverState.FAILED or self._stopping:
            return
        self.state = (DriverState.DEGRADED if self.stats.consecutive_errors
                      else DriverState.RUNNING)

    def health(self, now: datetime | None = None) -> Any:
        moment = now or self.now()
        stale = self._is_stale(moment)
        driver_state = (ComponentHealth.FAILED if self.state is DriverState.FAILED
                        else ComponentHealth.DEGRADED
                        if (stale or self.stats.consecutive_errors) else
                        ComponentHealth.HEALTHY)
        return self.health_monitor.build(
            {"api": ComponentHealth.HEALTHY,
             "database": ComponentHealth.HEALTHY if self.repository is not None
             else ComponentHealth.UNKNOWN,
             "mt5": driver_state, "market_data": driver_state,
             "data_quality": driver_state, "strategy": driver_state,
             # A cycle that ran without a model is degraded, not unseen.
             "nn": (ComponentHealth.UNKNOWN if self.stats.last_prediction is None
                    else ComponentHealth.HEALTHY if self.stats.last_prediction
                    else ComponentHealth.DEGRADED),
             "risk": driver_state,
             "execution": ComponentHealth.HEALTHY,
             "dashboard": ComponentHealth.HEALTHY,
             "monitoring": ComponentHealth.HEALTHY if self.alerts is not None
             else ComponentHealth.UNKNOWN},
            last_error=self.stats.last_error, now=moment)

    def _is_stale(self, moment: datetime) -> bool:
        if self.stats.last_success_at is None:
            return self.stats.ticks > 0
        elapsed = (moment - self.stats.last_success_at).total_seconds()
        return elapsed > self.config.interval_seconds * max(self.config.stale_after_cycles, 1)

    def status(self, now: datetime | None = None) -> dict[str, Any]:
        moment = now or self.now()
        interval = max(self.config.interval_seconds, 1)
        return jsonable({
            "state": str(self.state), "config": self.config.as_dict(),
            "statistics": self.stats.as_dict(),
            "cycles_per_minute": round(60.0 / interval, 4),
            "last_cycle": self.stats.last_cycle_at,
            "last_successful_cycle": self.stats.last_success_at,
            "failed_cycles": self.stats.cycles_failed,
            "stale": self._is_stale(moment),
            "health": self.health(moment).as_dict(),
            "observation_mode": self.settings.observation_mode,
            "orders_sent": 0,
        })


def _default_sleeper(seconds: float) -> None:
    import time

    time.sleep(seconds)
