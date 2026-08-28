"""Shadow signals and shadow outcomes (sections 2, 3 and 4).

A shadow signal is not a second pipeline. It is a *recording* of the one the DEMO
path already produced: the same market data, features, NN inference, strategy
decision, risk evaluation and execution proposal, taken from the same
`GateChainDecision`. The only difference is the last step — SHADOW stops before
the broker call, DEMO does not.

That is why `ShadowRecorder.record()` takes the request and the decision rather
than a symbol and a price: there is no way to mint a shadow record without the
artefacts DEMO used, so the two cannot drift apart by construction.

Nothing in this module can send an order. It holds no client, no guard and no
transport, and `orders_sent` is a constant 0.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

SHADOW_SOURCE = "SHADOW"
SHADOW_VERSION = "phase17.shadow.v1"

# Why a shadow signal never became a DEMO trade. A shadow record exists either
# way, which is the point: the blocked ones are the population DEMO never saw.
NOT_EXECUTED_BLOCKED = "GATES_BLOCKED"
NOT_EXECUTED_MODE = "MODE_DOES_NOT_EXECUTE"
NOT_EXECUTED_PENDING = "AWAITING_APPROVAL"


class ShadowStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    ABANDONED = "ABANDONED"


def shadow_signal_id(request_id: str) -> str:
    """Derived from the execution request id, so the pairing is not bookkeeping.

    A shadow record and its DEMO counterpart are two views of one decision. Making
    the id a function of the request id means a shadow signal can always be found
    from a DEMO trade and vice versa, even if one of the two rows is missing.
    """
    return hashlib.sha256(f"shadow|{request_id}".encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True, slots=True)
class ShadowSignal:
    """Section 3, field for field."""

    shadow_signal_id: str
    demo_execution_request_id: str
    symbol: str
    timestamp: datetime
    side: str
    entry: float | None
    stop_loss: float | None
    take_profit: float | None
    strategy: str | None = None
    strategy_version: str | None = None
    model: str | None = None
    model_version: str | None = None
    feature_version: str | None = None
    confidence: float | None = None
    risk_snapshot_id: str | None = None
    risk_state: str | None = None
    session: str | None = None
    regime: str | None = None
    timeframe: str | None = None
    volume: float = 0.0
    spread: float | None = None
    signal_timeframe: str | None = None
    approved: bool = False
    # Would the trade have been taken had execution been armed? This is the
    # figure SHADOW exists to produce: `approved` also reflects the mode, and in
    # SHADOW the mode always refuses.
    decision_approved: bool = False
    executed: bool = False
    not_executed_reason: str | None = None
    blocked_reasons: tuple[str, ...] = ()
    gates: dict[str, Any] = field(default_factory=dict)
    status: ShadowStatus = ShadowStatus.OPEN
    source: str = SHADOW_SOURCE
    version: str = SHADOW_VERSION

    # There is no transport in this module.
    orders_sent: int = 0

    @property
    def directional(self) -> bool:
        return str(self.side).upper() in {"BUY", "SELL", "LONG", "SHORT"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "shadow_signal_id": self.shadow_signal_id,
            "demo_execution_request_id": self.demo_execution_request_id,
            "symbol": self.symbol, "timestamp": self.timestamp, "side": self.side,
            "entry": self.entry, "stop_loss": self.stop_loss, "take_profit": self.take_profit,
            "strategy": self.strategy, "strategy_version": self.strategy_version,
            "model": self.model, "model_version": self.model_version,
            "feature_version": self.feature_version, "confidence": self.confidence,
            "risk_snapshot_id": self.risk_snapshot_id, "risk_state": self.risk_state,
            "session": self.session, "regime": self.regime, "timeframe": self.timeframe,
            "signal_timeframe": self.signal_timeframe, "volume": self.volume,
            "spread": self.spread, "approved": self.approved,
            "decision_approved": self.decision_approved, "executed": self.executed,
            "not_executed_reason": self.not_executed_reason,
            "blocked_reasons": list(self.blocked_reasons), "gates": dict(self.gates),
            "status": str(self.status), "source": self.source, "version": self.version,
            "orders_sent": 0,
        }


@dataclass(frozen=True, slots=True)
class ShadowOutcome:
    """Section 4. What the signal would have produced, net of modelled cost.

    `net_expected_pnl` is the primary figure. An expected move smaller than the
    spread and the estimated slippage is not an expected profit, and reporting
    the gross number as the headline would be the most flattering possible lie.
    """

    shadow_signal_id: str
    symbol: str
    side: str
    expected_entry: float
    expected_exit: float
    expected_pnl: float
    mfe: float
    mae: float
    duration_seconds: float
    spread: float
    slippage_estimate: float
    commission_estimate: float
    net_expected_pnl: float
    exit_reason: str | None = None
    resolved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    bars: int = 0
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def profitable(self) -> bool:
        """Net, always. A gross win that does not clear cost is not a win."""
        return self.net_expected_pnl > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "shadow_signal_id": self.shadow_signal_id, "symbol": self.symbol,
            "side": self.side, "expected_entry": self.expected_entry,
            "expected_exit": self.expected_exit, "expected_pnl": round(self.expected_pnl, 8),
            "mfe": round(self.mfe, 8), "mae": round(self.mae, 8),
            "duration_seconds": round(self.duration_seconds, 1), "spread": self.spread,
            "slippage_estimate": self.slippage_estimate,
            "commission_estimate": self.commission_estimate,
            "net_expected_pnl": round(self.net_expected_pnl, 8),
            "profitable": self.profitable, "exit_reason": self.exit_reason,
            "resolved_at": self.resolved_at, "bars": self.bars,
            "context": dict(self.context), "orders_sent": 0,
        }


class ShadowRecorder:
    """Mints shadow records from the artefacts the DEMO path already produced.

    `repository` is optional; without one the recorder still keeps every record in
    memory, so shadow trading works before any migration is applied.
    """

    def __init__(self, repository: Any = None, *, spread_cost: float | None = None,
                 slippage_estimate: float | None = None, commission: float | None = None):
        from config.settings import load_yaml

        config = load_yaml().get("phase_17", {}).get("shadow", {})
        self.repository = repository
        self.spread_cost = float(
            spread_cost if spread_cost is not None else config.get("spread", 0.0001))
        self.slippage_estimate = float(
            slippage_estimate if slippage_estimate is not None
            else config.get("slippage_estimate", 0.00002))
        self.commission = float(
            commission if commission is not None else config.get("commission", 0.0))
        self._signals: dict[str, ShadowSignal] = {}
        self._outcomes: dict[str, ShadowOutcome] = {}

    # ------------------------------------------------------------------ record
    def record(self, request: Any, decision: Any, context: Any = None, *,
               executed: bool = False, not_executed_reason: str | None = None) -> ShadowSignal:
        """One shadow record per DEMO candidate, minted from that candidate.

        Called from the shared proposal path, so a DEMO candidate without a
        shadow record is not a thing that can happen.
        """
        payload = request.as_dict() if hasattr(request, "as_dict") else dict(request or {})
        request_id = str(payload.get("request_id"))
        approved = bool(getattr(decision, "approved", False))
        decision_approved = bool(getattr(decision, "decision_approved", approved))
        reasons = tuple(str(reason) for reason in getattr(decision, "reasons", ()) or ())
        gates = {gate.name: gate.passed for gate in getattr(decision, "gates", ()) or ()}

        if not_executed_reason is None and not executed:
            # The decision verdict decides which of the two reasons is honest: a
            # signal the strategy refused is not "blocked by the mode".
            not_executed_reason = (NOT_EXECUTED_MODE if decision_approved
                                   else NOT_EXECUTED_BLOCKED)

        quote = getattr(context, "quote", None) or {}
        spread = None
        if quote.get("bid") is not None and quote.get("ask") is not None:
            spread = float(quote["ask"]) - float(quote["bid"])

        signal = ShadowSignal(
            shadow_signal_id=shadow_signal_id(request_id),
            demo_execution_request_id=request_id,
            symbol=str(payload.get("symbol") or ""),
            timestamp=payload.get("timestamp") or datetime.now(timezone.utc),
            side=str(payload.get("side") or ""),
            entry=payload.get("price"),
            stop_loss=payload.get("stop_loss"),
            take_profit=payload.get("take_profit"),
            strategy=payload.get("strategy_id"),
            strategy_version=payload.get("strategy_version"),
            model=payload.get("model_version"),
            model_version=payload.get("model_version"),
            feature_version=payload.get("feature_version"),
            confidence=getattr(context, "model_confidence", None),
            risk_snapshot_id=payload.get("risk_snapshot_id"),
            risk_state=_risk_state(context),
            session=getattr(context, "session", None),
            regime=getattr(context, "regime", None),
            timeframe=getattr(context, "timeframe", None),
            signal_timeframe=getattr(context, "signal_timeframe", None),
            volume=float(payload.get("volume") or 0.0),
            spread=spread,
            approved=approved, decision_approved=decision_approved, executed=bool(executed),
            not_executed_reason=None if executed else not_executed_reason,
            blocked_reasons=reasons, gates=gates,
        )
        return self._save(signal)

    def mark_executed(self, request_id: str) -> ShadowSignal | None:
        """A shadow record whose DEMO twin actually reached the broker."""
        signal = self.get(shadow_signal_id(str(request_id)))
        if signal is None:
            return None
        return self._save(replace(signal, executed=True, not_executed_reason=None))

    def _save(self, signal: ShadowSignal) -> ShadowSignal:
        self._signals[signal.shadow_signal_id] = signal
        if self.repository is not None and hasattr(self.repository, "save_shadow_signal"):
            try:
                self.repository.save_shadow_signal(signal)
            except Exception:
                logger.exception("failed to persist shadow signal %s", signal.shadow_signal_id)
        return signal

    # ----------------------------------------------------------------- resolve
    def resolve(self, signal: ShadowSignal, *, exit_price: float, exit_time: datetime,
                highs: Sequence[float] | None = None, lows: Sequence[float] | None = None,
                exit_reason: str | None = None, spread: float | None = None,
                slippage_estimate: float | None = None,
                commission: float | None = None) -> ShadowOutcome | None:
        """Compute what the signal would have produced (section 4).

        `highs`/`lows` are the path between entry and exit. Without them MFE and
        MAE are bounded by the exit itself rather than invented, which understates
        the excursions and is the safe direction to be wrong in.
        """
        if signal.entry is None or not signal.directional:
            return None
        sign = -1.0 if str(signal.side).upper() in {"SELL", "SHORT"} else 1.0
        entry, exit_ = float(signal.entry), float(exit_price)
        gross = (exit_ - entry) * sign

        highs = list(highs or [exit_])
        lows = list(lows or [exit_])
        if sign > 0:
            mfe = max(max(highs) - entry, 0.0)
            mae = min(min(lows) - entry, 0.0)
        else:
            mfe = max(entry - min(lows), 0.0)
            mae = min(entry - max(highs), 0.0)

        cost_spread = float(spread if spread is not None else (signal.spread or self.spread_cost))
        cost_slip = float(slippage_estimate if slippage_estimate is not None
                          else self.slippage_estimate)
        cost_commission = float(commission if commission is not None else self.commission)
        duration = max(0.0, (exit_time - signal.timestamp).total_seconds())

        outcome = ShadowOutcome(
            shadow_signal_id=signal.shadow_signal_id, symbol=signal.symbol, side=signal.side,
            expected_entry=entry, expected_exit=exit_, expected_pnl=gross, mfe=mfe, mae=mae,
            duration_seconds=duration, spread=cost_spread, slippage_estimate=cost_slip,
            commission_estimate=cost_commission,
            net_expected_pnl=gross - abs(cost_spread) - abs(cost_slip) - abs(cost_commission),
            exit_reason=exit_reason, resolved_at=exit_time, bars=len(highs),
            context={"executed": signal.executed, "approved": signal.approved,
                     "session": signal.session, "regime": signal.regime})
        self._outcomes[signal.shadow_signal_id] = outcome
        self._signals[signal.shadow_signal_id] = replace(signal, status=ShadowStatus.RESOLVED)
        if self.repository is not None and hasattr(self.repository, "save_shadow_outcome"):
            try:
                self.repository.save_shadow_outcome(self._signals[signal.shadow_signal_id], outcome)
            except Exception:
                logger.exception("failed to persist shadow outcome %s", signal.shadow_signal_id)
        return outcome

    def abandon(self, shadow_id: str, reason: str = "NO_EXIT_OBSERVED") -> ShadowSignal | None:
        """A signal that never reached an exit is abandoned, never assumed flat."""
        signal = self.get(shadow_id)
        if signal is None:
            return None
        return self._save(replace(signal, status=ShadowStatus.ABANDONED,
                                  not_executed_reason=signal.not_executed_reason or reason))

    # ------------------------------------------------------------------ reads
    def get(self, shadow_id: str) -> ShadowSignal | None:
        return self._signals.get(str(shadow_id))

    def for_request(self, request_id: str) -> ShadowSignal | None:
        return self.get(shadow_signal_id(str(request_id)))

    def outcome_for(self, shadow_id: str) -> ShadowOutcome | None:
        return self._outcomes.get(str(shadow_id))

    @property
    def signals(self) -> tuple[ShadowSignal, ...]:
        return tuple(self._signals.values())

    @property
    def outcomes(self) -> tuple[ShadowOutcome, ...]:
        return tuple(self._outcomes.values())

    def open_signals(self) -> tuple[ShadowSignal, ...]:
        return tuple(signal for signal in self._signals.values()
                     if signal.status is ShadowStatus.OPEN)

    def summary(self) -> dict[str, Any]:
        signals = self.signals
        executed = [signal for signal in signals if signal.executed]
        return {"signals": len(signals), "executed": len(executed),
                "shadow_only": len(signals) - len(executed),
                "resolved": len(self._outcomes),
                "orders_sent": 0, "source": SHADOW_SOURCE, "version": SHADOW_VERSION}


def _risk_state(context: Any) -> str | None:
    allowed = getattr(context, "risk_allowed", None)
    if allowed is None:
        return None
    return "APPROVED" if allowed else "BLOCKED"
