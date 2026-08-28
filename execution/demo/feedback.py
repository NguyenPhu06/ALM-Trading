"""AI feedback after a DEMO trade closes (section 30).

The outcome of a closed DEMO trade is sent to the observation/performance
pipeline, and that is the whole of it. Nothing here fits a model, updates a
weight, promotes a champion or schedules a training run.

That restriction is a Phase 13/14 invariant, not a Phase 16 preference:
`AI_ONLINE_LEARNING_ENABLED` and `AI_AUTOMATIC_TRAINING` are both refused at
startup, and a live trade result is exactly the kind of input that would tempt a
system into learning inside the market loop. `retrained` is therefore a constant
False on every record this module produces, and a test asserts it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

EVIDENCE_SOURCE = "DEMO_EXECUTION"
FEEDBACK_VERSION = "phase16.feedback.v1"


@dataclass(frozen=True, slots=True)
class DemoTradeFeedback:
    """One closed DEMO trade, in the shape the performance pipeline consumes."""

    trade_id: str
    symbol: str
    direction: str
    entry_price: float | None
    exit_price: float | None
    net_pnl: float | None
    gross_pnl: float | None
    mae: float | None
    mfe: float | None
    exit_reason: str | None
    holding_seconds: float | None
    spread: float | None = None
    slippage: float | None = None
    commission: float = 0.0
    swap: float = 0.0
    session: str | None = None
    regime: str | None = None
    model_version: str | None = None
    strategy_version: str | None = None
    feature_version: str | None = None
    nn_confidence: float | None = None
    predicted_direction: str | None = None
    evidence: str = EVIDENCE_SOURCE
    version: str = FEEDBACK_VERSION
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # There is no code path in this module that trains anything.
    retrained: bool = False
    promoted: bool = False

    @property
    def prediction_correct(self) -> bool | None:
        """Whether the network called the direction, when both are known."""
        if not self.predicted_direction or self.net_pnl is None:
            return None
        predicted_long = str(self.predicted_direction).upper() in {"UP", "BUY", "LONG"}
        traded_long = str(self.direction).upper() in {"BUY", "LONG"}
        return (predicted_long == traded_long) == (self.net_pnl > 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trade_id": self.trade_id, "symbol": self.symbol, "direction": self.direction,
            "entry_price": self.entry_price, "exit_price": self.exit_price,
            "net_pnl": self.net_pnl, "gross_pnl": self.gross_pnl,
            "mae": self.mae, "mfe": self.mfe, "exit_reason": self.exit_reason,
            "holding_seconds": self.holding_seconds, "spread": self.spread,
            "slippage": self.slippage, "commission": self.commission, "swap": self.swap,
            "session": self.session, "regime": self.regime,
            "model_version": self.model_version, "strategy_version": self.strategy_version,
            "feature_version": self.feature_version, "nn_confidence": self.nn_confidence,
            "predicted_direction": self.predicted_direction,
            "prediction_correct": self.prediction_correct,
            "evidence": self.evidence, "version": self.version, "timestamp": self.timestamp,
            "retrained": False, "promoted": False,
        }


class DemoFeedbackPublisher:
    """Sends a closed trade to the observation/performance store. It never trains.

    `repository` is any object exposing `save_performance(dict)` — the Phase 12
    ObservationRepository does — so DEMO results land in the same store as
    forward observations and can be compared with them directly.
    """

    def __init__(self, repository: Any = None, *, alerts: Any = None):
        self.repository = repository
        self.alerts = alerts
        self._published: list[DemoTradeFeedback] = []

    @staticmethod
    def from_journal(entry: Any, *, exit_price: float | None = None,
                     holding_seconds: float | None = None) -> DemoTradeFeedback:
        """Build the feedback record from a closed journal entry."""
        payload = entry.as_dict() if hasattr(entry, "as_dict") else dict(entry or {})
        result = payload.get("mt5_result") or {}
        prediction = payload.get("nn_prediction") or {}
        # `as_dict` is JSON-shaped, so its timestamps are strings. Read the
        # durations off the record itself rather than parsing them back.
        opened = getattr(entry, "opened_at", None)
        closed = getattr(entry, "closed_at", None)
        if holding_seconds is None and opened and closed:
            holding_seconds = (closed - opened).total_seconds()
        return DemoTradeFeedback(
            trade_id=str(payload.get("trade_id")), symbol=str(payload.get("symbol") or ""),
            direction=str(payload.get("direction") or ""),
            entry_price=result.get("filled_price"),
            exit_price=exit_price if exit_price is not None else result.get("exit_price"),
            net_pnl=payload.get("pnl"), gross_pnl=payload.get("gross_pnl"),
            mae=payload.get("mae"), mfe=payload.get("mfe"),
            exit_reason=payload.get("exit_reason"), holding_seconds=holding_seconds,
            spread=(payload.get("market_snapshot") or {}).get("spread"),
            slippage=payload.get("slippage"),
            commission=float(payload.get("commission") or 0.0),
            swap=float(payload.get("swap") or 0.0),
            session=payload.get("session"), regime=payload.get("regime"),
            model_version=payload.get("model_version"),
            strategy_version=payload.get("strategy_version"),
            feature_version=payload.get("feature_version"),
            nn_confidence=prediction.get("confidence"),
            predicted_direction=prediction.get("direction") or prediction.get("predicted_class"))

    def publish(self, feedback: DemoTradeFeedback) -> DemoTradeFeedback:
        """Record the outcome. Returns the record; training is never triggered."""
        self._published.append(feedback)
        if self.repository is not None and hasattr(self.repository, "save_performance"):
            try:
                self.repository.save_performance(feedback.as_dict())
            except Exception:
                logger.exception("failed to persist demo trade feedback %s", feedback.trade_id)
        logger.info("demo trade feedback recorded for %s (retrained=False)", feedback.trade_id)
        return feedback

    def publish_journal(self, entry: Any, **kwargs: Any) -> DemoTradeFeedback:
        return self.publish(self.from_journal(entry, **kwargs))

    @property
    def published(self) -> tuple[DemoTradeFeedback, ...]:
        return tuple(self._published)
