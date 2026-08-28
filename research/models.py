"""The unit of research evidence.

Every study in this package consumes `ResearchObservation` — one recorded
forward observation, reduced to what research needs and carrying the labels the
matrices slice on. It is built from what the Phase 14 loop already produced; no
study re-derives anything from price.

`net_pnl` is net of spread, commission, slippage and swap. Research never reads
a gross figure: a comparison made on gross returns would rank strategies by how
much they trade rather than by how much they earn.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

from ai.edge.evidence import EvidenceSource, require_forward

# Vocabularies the matrices slice on, in the order they are reported.
REGIMES = ("STRONG_BULL", "BULL", "RANGE", "BEAR", "STRONG_BEAR", "UNKNOWN")
SESSIONS = ("ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP", "OFF_SESSION",
            "CUSTOM")
TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")


@dataclass(frozen=True, slots=True)
class ResearchObservation:
    observation_id: str
    resolved_at: datetime
    net_pnl: float
    # what the strategy said and what happened
    predicted: str | None = None
    actual: str | None = None
    correct: bool | None = None
    confidence: float | None = None
    # excursions and cost
    mae: float | None = None
    mfe: float | None = None
    spread: float | None = None
    holding_time: float | None = None
    margin_used: float | None = None
    # slicing labels
    regime: str | None = None
    previous_regime: str | None = None
    session: str | None = None
    timeframe: str | None = None
    symbol: str | None = None
    # research labels
    strategy_id: str | None = None
    experiment_id: str | None = None
    dca_levels: int = 0
    exit_kind: str | None = None
    liquidity_event: str | None = None
    signals: dict[str, Any] = field(default_factory=dict)
    evidence: EvidenceSource = EvidenceSource.FORWARD_OBSERVATION
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def win(self) -> bool:
        """Net, never gross."""
        return self.net_pnl > 0

    @property
    def regime_transition(self) -> str | None:
        if not self.previous_regime or not self.regime:
            return None
        if self.previous_regime == self.regime:
            return None
        return f"{self.previous_regime}->{self.regime}"

    def labelled(self, **updates: Any) -> "ResearchObservation":
        return replace(self, **updates)

    def as_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "net_pnl": self.net_pnl, "predicted": self.predicted, "actual": self.actual,
            "correct": self.correct, "confidence": self.confidence, "mae": self.mae,
            "mfe": self.mfe, "spread": self.spread, "holding_time": self.holding_time,
            "margin_used": self.margin_used, "regime": self.regime,
            "previous_regime": self.previous_regime,
            "regime_transition": self.regime_transition, "session": self.session,
            "timeframe": self.timeframe, "symbol": self.symbol,
            "strategy_id": self.strategy_id, "experiment_id": self.experiment_id,
            "dca_levels": self.dca_levels, "exit_kind": self.exit_kind,
            "liquidity_event": self.liquidity_event, "signals": dict(self.signals),
            "evidence": str(self.evidence),
        }

    # ------------------------------------------------------------- adapters
    @classmethod
    def from_outcome(cls, observation: Any, outcome: Any, *,
                     strategy_id: str | None = None,
                     experiment_id: str | None = None,
                     previous_regime: str | None = None,
                     signals: Mapping[str, Any] | None = None) -> "ResearchObservation":
        """Build from a Phase 14 `Observation` + `ForwardOutcome` pair."""
        predicted = _read(outcome, "predicted_direction") or _read(observation, "direction")
        actual = _read(outcome, "actual_direction")
        correct = None
        if predicted and actual and predicted in {"UP", "DOWN"}:
            correct = predicted == actual
        context = _mapping(_read(observation, "context"))
        return cls(
            observation_id=str(_read(outcome, "observation_id")
                               or _read(observation, "observation_id") or ""),
            resolved_at=_read(outcome, "resolved_at"),
            net_pnl=float(_read(outcome, "net_hypothetical_pnl") or 0.0),
            predicted=predicted, actual=actual, correct=correct,
            confidence=_number(_read(observation, "nn_confidence")),
            mae=_number(_read(outcome, "mae")), mfe=_number(_read(outcome, "mfe")),
            spread=_number(_read(outcome, "spread")),
            holding_time=_number(_read(outcome, "holding_time")),
            regime=_text(_read(observation, "market_regime")),
            previous_regime=previous_regime,
            session=_text(_read(observation, "session")),
            timeframe=_text(_read(observation, "timeframe")),
            symbol=_text(_read(observation, "symbol")),
            strategy_id=strategy_id, experiment_id=experiment_id,
            dca_levels=int(context.get("dca_levels") or 0),
            exit_kind=_text(context.get("exit_kind")),
            liquidity_event=_text(context.get("liquidity_event")),
            signals=dict(signals or context.get("signals") or {}))

    @classmethod
    def from_row(cls, row: Any, **overrides: Any) -> "ResearchObservation":
        """Build from a persisted `observation_outcomes` row joined to its observation."""
        payload = dict(getattr(row, "outcome_json", None) or {})
        values = {
            "observation_id": row.observation_id, "resolved_at": row.resolved_at,
            "net_pnl": float(row.net_hypothetical_pnl or 0.0),
            "predicted": payload.get("predicted_direction"),
            "actual": payload.get("actual_direction"),
            "mae": row.mae, "mfe": row.mfe, "spread": row.spread,
            "holding_time": row.holding_time, "regime": row.regime,
            "session": row.session, "timeframe": row.timeframe, "symbol": row.symbol,
        }
        values.update(overrides)
        predicted, actual = values.get("predicted"), values.get("actual")
        if values.get("correct") is None and predicted in {"UP", "DOWN"} and actual:
            values["correct"] = predicted == actual
        return cls(**values)


def require_forward_only(observations: Iterable[ResearchObservation]) -> list[
        ResearchObservation]:
    """Section 6: research reads forward evidence, and nothing else.

    Checked per observation rather than once for the batch, so a single
    backtest row mixed into a forward set is refused by name instead of
    silently averaging into the result.
    """
    rows = list(observations)
    for row in rows:
        require_forward(row.evidence)
    return rows


def segment(observations: Sequence[ResearchObservation], attribute: str,
            known: Sequence[str] = ()) -> dict[str, list[ResearchObservation]]:
    """Group by a slicing label, keeping every known bucket even when empty."""
    grouped: dict[str, list[ResearchObservation]] = {name: [] for name in known}
    for row in observations:
        value = getattr(row, attribute, None)
        name = str(value or "UNKNOWN").upper()
        if known and name not in known:
            name = "CUSTOM" if "CUSTOM" in known else "UNKNOWN"
        grouped.setdefault(name, []).append(row)
    return grouped


def _read(source: Any, name: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(name)
    return getattr(source, name, None)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return str(value) if value is not None else None
