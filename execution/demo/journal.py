"""The DEMO trade journal (section 20).

Every DEMO trade records the whole chain of custody: what the market looked like,
what the features said, what the network predicted, what the strategy decided,
what risk allowed, what was requested, what the broker did, how the position
lived and why it ended — with the versions of everything attached.

The versions are the point. A journal entry without model, strategy and feature
versions cannot be replayed or attributed, so `complete` reports whether an entry
is actually usable as evidence rather than assuming it is.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from observation.snapshot import jsonable

REQUIRED_FIELDS = ("market_snapshot", "feature_snapshot", "strategy_decision", "risk_decision",
                   "execution_request", "execution_result")
REQUIRED_VERSIONS = ("model_version", "strategy_version", "feature_version")


@dataclass(frozen=True, slots=True)
class DemoTradeJournalEntry:
    trade_id: str
    request_id: str
    symbol: str
    direction: str
    timestamp: datetime
    market_snapshot: dict[str, Any] = field(default_factory=dict)
    feature_snapshot: dict[str, Any] = field(default_factory=dict)
    nn_prediction: dict[str, Any] | None = None
    strategy_decision: dict[str, Any] = field(default_factory=dict)
    risk_decision: dict[str, Any] = field(default_factory=dict)
    execution_request: dict[str, Any] = field(default_factory=dict)
    execution_result: dict[str, Any] = field(default_factory=dict)
    mt5_result: dict[str, Any] = field(default_factory=dict)
    position_lifecycle: tuple[dict[str, Any], ...] = ()
    exit_reason: str | None = None
    pnl: float | None = None
    gross_pnl: float | None = None
    mae: float | None = None
    mfe: float | None = None
    session: str | None = None
    regime: str | None = None
    model_version: str | None = None
    strategy_version: str | None = None
    feature_version: str | None = None
    broker_ticket: int | None = None
    commission: float = 0.0
    swap: float = 0.0
    slippage: float | None = None
    opened_at: datetime | None = None
    closed_at: datetime | None = None

    @property
    def closed(self) -> bool:
        return self.exit_reason is not None and self.closed_at is not None

    @property
    def missing(self) -> tuple[str, ...]:
        """Which mandatory sections and versions are absent."""
        gaps = [name for name in REQUIRED_FIELDS if not getattr(self, name)]
        gaps.extend(name for name in REQUIRED_VERSIONS if not getattr(self, name))
        return tuple(gaps)

    @property
    def complete(self) -> bool:
        return not self.missing

    def as_dict(self) -> dict[str, Any]:
        return jsonable({
            "trade_id": self.trade_id, "request_id": self.request_id, "symbol": self.symbol,
            "direction": self.direction, "timestamp": self.timestamp,
            "market_snapshot": self.market_snapshot, "feature_snapshot": self.feature_snapshot,
            "nn_prediction": self.nn_prediction, "strategy_decision": self.strategy_decision,
            "risk_decision": self.risk_decision, "execution_request": self.execution_request,
            "execution_result": self.execution_result, "mt5_result": self.mt5_result,
            "position_lifecycle": list(self.position_lifecycle), "exit_reason": self.exit_reason,
            "pnl": self.pnl, "gross_pnl": self.gross_pnl, "mae": self.mae, "mfe": self.mfe,
            "session": self.session, "regime": self.regime,
            "model_version": self.model_version, "strategy_version": self.strategy_version,
            "feature_version": self.feature_version, "broker_ticket": self.broker_ticket,
            "commission": self.commission, "swap": self.swap, "slippage": self.slippage,
            "opened_at": self.opened_at, "closed_at": self.closed_at,
            "closed": self.closed, "complete": self.complete, "missing": list(self.missing),
        })


class DemoTradeJournal:
    """Builds and closes journal entries. Optionally writes each change through."""

    def __init__(self, repository: Any = None):
        self.repository = repository
        self._entries: dict[str, DemoTradeJournalEntry] = {}

    def _save(self, entry: DemoTradeJournalEntry) -> DemoTradeJournalEntry:
        self._entries[entry.trade_id] = entry
        if self.repository is not None and hasattr(self.repository, "save_journal"):
            self.repository.save_journal(entry)
        return entry

    def open(self, *, request: Any, result: Any, decision: Any = None,
             market_snapshot: dict[str, Any] | None = None,
             feature_snapshot: dict[str, Any] | None = None,
             nn_prediction: dict[str, Any] | None = None,
             strategy_decision: dict[str, Any] | None = None,
             risk_decision: dict[str, Any] | None = None,
             session: str | None = None, regime: str | None = None,
             now: datetime | None = None) -> DemoTradeJournalEntry:
        """Create the entry at fill time, with everything known so far."""
        moment = now or datetime.now(timezone.utc)
        request_payload = request.as_dict() if hasattr(request, "as_dict") else dict(request or {})
        result_payload = result.as_dict() if hasattr(result, "as_dict") else dict(result or {})
        filled = result_payload.get("filled_price")
        requested = result_payload.get("requested_price")
        entry = DemoTradeJournalEntry(
            trade_id=str(request_payload.get("request_id")),
            request_id=str(request_payload.get("request_id")),
            symbol=str(request_payload.get("symbol") or ""),
            direction=str(request_payload.get("side") or ""),
            timestamp=moment,
            market_snapshot=dict(market_snapshot or {}),
            feature_snapshot=dict(feature_snapshot or {}),
            nn_prediction=dict(nn_prediction) if nn_prediction else None,
            strategy_decision=dict(strategy_decision or {}),
            risk_decision=dict(risk_decision or {}),
            execution_request=request_payload,
            execution_result=decision.as_dict() if decision is not None and hasattr(decision, "as_dict") else {},
            mt5_result=result_payload,
            session=session, regime=regime,
            model_version=request_payload.get("model_version"),
            strategy_version=request_payload.get("strategy_version"),
            feature_version=request_payload.get("feature_version"),
            broker_ticket=result_payload.get("broker_ticket"),
            slippage=(abs(float(filled) - float(requested))
                      if filled is not None and requested is not None else None),
            opened_at=moment)
        # `execution_result` is the gate/guard verdict; `mt5_result` is the broker's.
        if not entry.execution_result:
            entry = replace(entry, execution_result=result_payload)
        return self._save(entry)

    def record_position(self, trade_id: str, snapshot: Any) -> DemoTradeJournalEntry | None:
        entry = self._entries.get(str(trade_id))
        if entry is None:
            return None
        payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else dict(snapshot or {})
        return self._save(replace(entry, position_lifecycle=entry.position_lifecycle + (payload,)))

    def close(self, trade_id: str, *, exit_reason: Any, pnl: float | None = None,
              gross_pnl: float | None = None, mae: float | None = None,
              mfe: float | None = None, commission: float | None = None,
              swap: float | None = None, now: datetime | None = None,
              **extra: Any) -> DemoTradeJournalEntry | None:
        """Close the entry. An exit without a reason is refused, not defaulted."""
        entry = self._entries.get(str(trade_id))
        if entry is None:
            return None
        if not str(exit_reason or "").strip():
            raise ValueError("closing a demo trade requires an exit reason")
        return self._save(replace(
            entry, exit_reason=str(exit_reason), pnl=pnl, gross_pnl=gross_pnl,
            mae=mae if mae is not None else entry.mae,
            mfe=mfe if mfe is not None else entry.mfe,
            commission=entry.commission if commission is None else float(commission),
            swap=entry.swap if swap is None else float(swap),
            closed_at=now or datetime.now(timezone.utc),
            mt5_result={**entry.mt5_result, **extra}))

    def get(self, trade_id: str) -> DemoTradeJournalEntry | None:
        return self._entries.get(str(trade_id))

    @property
    def entries(self) -> tuple[DemoTradeJournalEntry, ...]:
        return tuple(self._entries.values())

    def closed_entries(self) -> tuple[DemoTradeJournalEntry, ...]:
        return tuple(entry for entry in self._entries.values() if entry.closed)
