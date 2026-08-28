"""The observation lifecycle (sections 4 and 5).

One observation is created per cycle and walks a fixed path:

    CREATED -> FEATURES_CAPTURED -> NN_PREDICTED -> STRATEGY_EVALUATED
            -> RISK_EVALUATED -> OBSERVING -> HORIZON_REACHED
            -> OUTCOME_CALCULATED -> LABELED -> DATASET_READY

Every step is recorded, so a crash mid-way leaves a resumable record rather than
an ambiguous one. The four failure states are terminal: a failed observation is
never quietly retried into the dataset.

Nothing here places, modifies or cancels an order. An `Observation` is a record
of what the system saw and concluded, never an instruction.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from observation.snapshot import jsonable


class ObservationStatus(StrEnum):
    CREATED = "CREATED"
    FEATURES_CAPTURED = "FEATURES_CAPTURED"
    NN_PREDICTED = "NN_PREDICTED"
    STRATEGY_EVALUATED = "STRATEGY_EVALUATED"
    RISK_EVALUATED = "RISK_EVALUATED"
    OBSERVING = "OBSERVING"
    HORIZON_REACHED = "HORIZON_REACHED"
    OUTCOME_CALCULATED = "OUTCOME_CALCULATED"
    LABELED = "LABELED"
    DATASET_READY = "DATASET_READY"
    # failure states
    DATA_INVALID = "DATA_INVALID"
    MODEL_ERROR = "MODEL_ERROR"
    CALCULATION_ERROR = "CALCULATION_ERROR"
    TIMEOUT = "TIMEOUT"


FAILURE_STATES = frozenset({
    ObservationStatus.DATA_INVALID, ObservationStatus.MODEL_ERROR,
    ObservationStatus.CALCULATION_ERROR, ObservationStatus.TIMEOUT,
})

HAPPY_PATH: tuple[ObservationStatus, ...] = (
    ObservationStatus.CREATED, ObservationStatus.FEATURES_CAPTURED,
    ObservationStatus.NN_PREDICTED, ObservationStatus.STRATEGY_EVALUATED,
    ObservationStatus.RISK_EVALUATED, ObservationStatus.OBSERVING,
    ObservationStatus.HORIZON_REACHED, ObservationStatus.OUTCOME_CALCULATED,
    ObservationStatus.LABELED, ObservationStatus.DATASET_READY,
)

# Forward only, one step at a time, plus a failure exit from any live state.
ALLOWED_TRANSITIONS: dict[ObservationStatus, frozenset[ObservationStatus]] = {
    state: frozenset({HAPPY_PATH[index + 1], *FAILURE_STATES})
    for index, state in enumerate(HAPPY_PATH[:-1])
}
ALLOWED_TRANSITIONS[ObservationStatus.DATASET_READY] = frozenset()
for _failed in FAILURE_STATES:
    ALLOWED_TRANSITIONS[_failed] = frozenset()


class LifecycleError(RuntimeError):
    """Raised when a caller tries to skip, repeat or reverse a lifecycle step."""


def deterministic_observation_id(cycle_id: str, symbol: str, horizon: str) -> str:
    digest = hashlib.sha256(f"{cycle_id}|{symbol.upper()}|{horizon}".encode()).hexdigest()
    return digest[:32]


@dataclass(frozen=True, slots=True)
class Observation:
    """Section 5. Immutable; each transition returns a new record."""

    observation_id: str
    cycle_id: str
    symbol: str
    timestamp: datetime
    entry_price: float | None = None
    direction: str = "WAIT"
    strategy: str | None = None
    market_regime: str | None = None
    session: str | None = None
    feature_version: str | None = None
    model_version: str | None = None
    nn_prediction: dict[str, Any] | None = None
    nn_confidence: float | None = None
    risk_state: str | None = None
    observation_horizon: str = "1h"
    status: ObservationStatus = ObservationStatus.CREATED
    timeframe: str = "M5"
    created_at: datetime | None = None
    updated_at: datetime | None = None
    failure_reason: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def deadline(self) -> datetime | None:
        """The moment the horizon elapses; before it, no outcome may be computed."""
        from ai.dataset.labels import resolve_horizon

        try:
            return self.timestamp + resolve_horizon(self.observation_horizon)
        except KeyError:
            return None

    @property
    def failed(self) -> bool:
        return self.status in FAILURE_STATES

    @property
    def terminal(self) -> bool:
        return self.failed or self.status is ObservationStatus.DATASET_READY

    def horizon_reached(self, now: datetime) -> bool:
        deadline = self.deadline
        return deadline is not None and now >= deadline

    def advance(self, status: ObservationStatus, *, now: datetime | None = None,
                failure_reason: str | None = None, **updates: Any) -> "Observation":
        target = ObservationStatus(status)
        allowed = ALLOWED_TRANSITIONS.get(self.status, frozenset())
        if target not in allowed:
            raise LifecycleError(f"{self.status} -> {target} is not an allowed transition")
        return replace(self, status=target, updated_at=now or _utcnow(),
                       failure_reason=failure_reason, **updates)

    def fail(self, status: ObservationStatus, reason: str, *,
             now: datetime | None = None) -> "Observation":
        if ObservationStatus(status) not in FAILURE_STATES:
            raise LifecycleError(f"{status} is not a failure state")
        return self.advance(status, now=now, failure_reason=str(reason))

    def as_dict(self) -> dict[str, Any]:
        return jsonable({
            "observation_id": self.observation_id, "cycle_id": self.cycle_id,
            "symbol": self.symbol, "timestamp": self.timestamp,
            "entry_price": self.entry_price, "direction": self.direction,
            "strategy": self.strategy, "market_regime": self.market_regime,
            "session": self.session, "feature_version": self.feature_version,
            "model_version": self.model_version, "nn_prediction": self.nn_prediction,
            "nn_confidence": self.nn_confidence, "risk_state": self.risk_state,
            "observation_horizon": self.observation_horizon, "status": str(self.status),
            "timeframe": self.timeframe, "created_at": self.created_at,
            "updated_at": self.updated_at, "failure_reason": self.failure_reason,
            "deadline": self.deadline, "context": self.context,
        })


def observation_from_cycle(result: Any, *, horizon: str, timeframe: str = "M5",
                           now: datetime | None = None,
                           cycle_id: str | None = None) -> Observation:
    """Build the record from a completed `ObservationResult`.

    The cycle already did the work; this only names what it produced. Any stage
    the cycle could not reach leaves its field None rather than a default value.

    `cycle_id` overrides the cycle's own random id so the driver can key an
    observation on the deterministic (symbol, timeframe, candle) identity that
    makes re-running a tick idempotent.
    """
    moment = now or _utcnow()
    key = cycle_id or result.cycle_id
    snapshot = getattr(result, "snapshot", None)
    prediction = getattr(snapshot, "neural_network", None) if snapshot else None
    strategy = dict(getattr(snapshot, "strategy", {}) or {}) if snapshot else {}
    risk = dict(getattr(snapshot, "risk", {}) or {}) if snapshot else {}
    market = dict(getattr(snapshot, "market_data", {}) or {}) if snapshot else {}
    session = (dict(getattr(snapshot, "session", {}) or {}).get("session")
               if snapshot else None)
    regime = getattr(result, "regime", None)

    entry = market.get("mid_price")
    return Observation(
        observation_id=deterministic_observation_id(key, result.symbol, horizon),
        cycle_id=key, symbol=result.symbol.upper(), timestamp=result.timestamp,
        entry_price=float(entry) if entry is not None else None,
        direction=str(getattr(result, "signal", "WAIT")),
        strategy=strategy.get("decision"),
        market_regime=str(regime.regime) if regime is not None else None,
        session=session,
        feature_version=getattr(snapshot, "feature_version", None) if snapshot else None,
        model_version=(prediction or {}).get("model_version"),
        nn_prediction=dict(prediction) if prediction else None,
        nn_confidence=(float(prediction["confidence"])
                       if prediction and prediction.get("confidence") is not None else None),
        risk_state=("APPROVED" if risk.get("risk_allowed") else "BLOCKED") if risk else None,
        observation_horizon=horizon, timeframe=timeframe,
        created_at=moment, updated_at=moment,
        context={"spread": (dict(getattr(snapshot, "spread", {}) or {}).get("spread")
                            if snapshot else None),
                 "strategy_confidence": strategy.get("confidence")},
    )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
