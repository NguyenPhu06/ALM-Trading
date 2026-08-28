"""Shared fixtures for the Phase 14 forward observation tests."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from observation.lifecycle import Observation, ObservationStatus
from observation.outcome import ForwardOutcome
from observation.simulation import SignalAction
from observation.snapshot import FeatureSnapshot

NOW = datetime(2026, 8, 27, 12, tzinfo=timezone.utc)
TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")


# --------------------------------------------------------------- fake cycle
@dataclass
class FakeResult:
    """The subset of `ObservationResult` the driver reads."""

    cycle_id: str
    symbol: str
    timestamp: datetime
    halted: bool = False
    reasons: tuple[str, ...] = ()
    signal: Any = SignalAction.BUY
    snapshot: Any = None
    regime: Any = None
    orders_sent: int = 0


@dataclass
class FakeRegime:
    regime: str = "BULL"


def snapshot(symbol: str = "EURUSD", *, timestamp: datetime = NOW, price: float = 1.1000,
             confidence: float = 0.80, session: str = "LONDON",
             decision: str = "SIMULATE") -> FeatureSnapshot:
    return FeatureSnapshot(
        cycle_id="cycle", symbol=symbol, timestamp=timestamp,
        market_data={"mid_price": price, "bid": price - 0.00005, "ask": price + 0.00005},
        spread={"spread": 0.00010}, session={"session": session},
        regime={"regime": "BULL"},
        neural_network={"prob_up": 0.80, "prob_down": 0.15, "prob_neutral": 0.05,
                        "confidence": confidence, "model_version": "multitask_mlp.v1",
                        "feature_version": "features_v1", "timestamp": timestamp},
        strategy={"decision": decision, "confidence": 0.7, "direction": "LONG"},
        risk={"risk_allowed": True, "reason_codes": []})


class FakeCycle:
    """Records what it was asked for; never touches a broker."""

    def __init__(self, *, results: Sequence[Any] = (), error: Exception | None = None,
                 timestamp: datetime = NOW, signal: Any = SignalAction.BUY,
                 halted: bool = False, confidence: float = 0.80):
        self.results = list(results)
        self.error = error
        self.timestamp = timestamp
        self.signal = signal
        self.halted = halted
        self.confidence = confidence
        self.calls: list[str] = []

    def run(self, symbol: str) -> Any:
        self.calls.append(symbol)
        if self.error is not None:
            raise self.error
        if self.results:
            return self.results.pop(0)
        return FakeResult(
            cycle_id=f"random-{len(self.calls)}", symbol=symbol, timestamp=self.timestamp,
            halted=self.halted, reasons=("HALTED",) if self.halted else (),
            signal=self.signal, regime=FakeRegime(),
            snapshot=snapshot(symbol, timestamp=self.timestamp,
                              confidence=self.confidence))


class RecordingAlerts:
    """Captures router calls without needing an AlertEngine."""

    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __getattr__(self, name: str):
        def handler(**kwargs: Any):
            self.calls.append((name, kwargs))
            return ()
        return handler

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]


# ------------------------------------------------------------------ candles
def candles(count: int, *, start: datetime, step_minutes: int = 5, drift: float = 0.00004,
            base: float = 1.1000) -> list[dict[str, Any]]:
    rows = []
    for index in range(count):
        stamp = start + timedelta(minutes=step_minutes * (index + 1))
        price = base + drift * index
        rows.append({"timestamp": stamp, "open": price, "close": price + drift,
                     "high": price + abs(drift) + 0.00020,
                     "low": price - abs(drift) - 0.00020})
    return rows


def candle_loader(rows: Sequence[dict[str, Any]]):
    def load(symbol: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        return [row for row in rows if start < row["timestamp"] <= end]
    return load


# ------------------------------------------------------------- observations
def observation(index: int = 0, *, timestamp: datetime = NOW, direction: str = "BUY",
                horizon: str = "1h", status: ObservationStatus = ObservationStatus.OBSERVING,
                confidence: float = 0.80, regime: str = "BULL", session: str = "LONDON",
                price: float = 1.1000, timeframe: str = "M5") -> Observation:
    return Observation(
        observation_id=f"obs-{index}", cycle_id=f"cycle-{index}", symbol="EURUSD",
        timestamp=timestamp, entry_price=price, direction=direction, strategy="SIMULATE",
        market_regime=regime, session=session, feature_version="features_v1",
        model_version="multitask_mlp.v1",
        nn_prediction={"prob_up": 0.8, "confidence": confidence},
        nn_confidence=confidence, risk_state="APPROVED", observation_horizon=horizon,
        status=status, timeframe=timeframe, created_at=timestamp, updated_at=timestamp,
        context={"spread": 0.00010})


def outcome(index: int = 0, *, net: float = 0.0005, resolved_at: datetime = NOW,
            direction: str = "BUY", future_return: float | None = None,
            regime: str = "BULL", session: str = "LONDON",
            timeframe: str = "M5") -> ForwardOutcome:
    gross = future_return if future_return is not None else net + 0.00012
    # future_return is signed by the observed direction; the price move is not.
    sign = -1.0 if direction.upper() in {"SELL", "SHORT"} else 1.0
    return ForwardOutcome(
        observation_id=f"obs-{index}", symbol="EURUSD", horizon="1h", direction=direction,
        entry_price=1.1000, future_price=1.1000 * (1 + sign * gross), future_return=gross,
        mfe=abs(gross) + 0.0002, mae=-abs(gross) - 0.0001,
        maximum_favorable_excursion=abs(gross) + 0.0002,
        maximum_adverse_excursion=-abs(gross) - 0.0001,
        hypothetical_pnl=gross, holding_time=3600.0, spread=0.00010,
        estimated_cost=0.00012, net_hypothetical_pnl=net, resolved_at=resolved_at,
        bars=12, context={"regime": regime, "session": session, "timeframe": timeframe})


@dataclass
class EntrySource:
    """An outcome-like row carrying its own segment labels, for the edge detector."""

    observation_id: str
    net_hypothetical_pnl: float
    regime: str = "BULL"
    session: str = "LONDON"
    timeframe: str = "M5"
    context: dict[str, Any] = field(default_factory=dict)


def entries(count: int, *, net: float = 0.0004, regimes: Sequence[str] = ("BULL",),
            sessions: Sequence[str] = ("LONDON",),
            timeframes: Sequence[str] = ("M5",)) -> list[EntrySource]:
    return [EntrySource(f"obs-{index}", net, regimes[index % len(regimes)],
                        sessions[index % len(sessions)], timeframes[index % len(timeframes)])
            for index in range(count)]


def performance_entries(count: int, *, net: float = 0.0004, correct: bool = True,
                        confidence: float = 0.8, now: datetime = NOW,
                        spacing_hours: int = 1, regimes: Sequence[str] = ("BULL",),
                        sessions: Sequence[str] = ("LONDON",),
                        timeframes: Sequence[str] = ("M5",)):
    from ai.performance.rolling import PerformanceEntry

    return [PerformanceEntry(
        observation_id=f"obs-{index}",
        resolved_at=now - timedelta(hours=spacing_hours * index), net_pnl=net,
        mae=-0.0003, mfe=0.0006, correct=correct, confidence=confidence, spread=0.00010,
        regime=regimes[index % len(regimes)], session=sessions[index % len(sessions)],
        timeframe=timeframes[index % len(timeframes)]) for index in range(count)]


BASELINES = {"random": 0.0, "majority": 0.0, "buy_and_hold": 0.00005, "momentum": 0.0001,
             "rsi": 0.00005, "ichimoku": 0.00008, "adx": 0.00002, "regime": 0.0001}


class MemoryRepository:
    """The driver's repository contract, in memory.

    Kept faithful to the real one in the ways that matter: upsert by observation
    id, duplicate detection by cycle id, and a due-query that only returns open
    observations whose horizon has elapsed.
    """

    def __init__(self):
        self.observations: dict[str, Observation] = {}
        self.outcomes: dict[str, Any] = {}
        self.labels: dict[str, Any] = {}

    # observations
    def save_observation(self, observation: Observation) -> Observation:
        self.observations[observation.observation_id] = observation
        return observation

    def observation_exists(self, *, cycle_id: str | None = None,
                           observation_id: str | None = None) -> bool:
        if observation_id is not None:
            return observation_id in self.observations
        return any(item.cycle_id == cycle_id for item in self.observations.values())

    def known_cycle_ids(self, limit: int = 5000) -> list[str]:
        return [item.cycle_id for item in self.observations.values()][:limit]

    def get_observation(self, observation_id: str) -> Observation | None:
        return self.observations.get(observation_id)

    def observations_due(self, *, now: datetime, limit: int = 200) -> list[Observation]:
        return [item for item in self.observations.values()
                if item.status is ObservationStatus.OBSERVING
                and item.horizon_reached(now)][:limit]

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.observations.values():
            counts[str(item.status)] = counts.get(str(item.status), 0) + 1
        return counts

    # outcomes and labels
    def save_outcome(self, observation: Observation, outcome: Any) -> Any:
        self.outcomes[outcome.observation_id] = outcome
        return outcome

    def dataset_row_exists(self, observation_id: str) -> bool:
        return observation_id in self.labels

    def attach_label(self, observation_id: str, label: Any,
                     *, future_price: float | None = None) -> Any:
        self.labels[observation_id] = label
        return label
