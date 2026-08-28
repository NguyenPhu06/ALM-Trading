"""Persistence for Phase 16 controlled DEMO trading.

Every payload passes through `scrub()` before it is written, so a credential
cannot reach these tables even if a caller puts one in a context dict.

Writes are idempotent by primary key where a record has a natural one — a
proposal and a journal entry are updated in place as they progress, so the row
always shows the current state while the audit log keeps the history.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    DemoDailyRiskRecord,
    DemoEmergencyEventRecord,
    DemoExecutionProposalRecord,
    DemoPaperComparisonRecord,
    DemoPositionSnapshotRecord,
    DemoTradeJournalRecord,
)
from database.repositories.mt5 import scrub


class DemoTradingRepository:
    def __init__(self, session: Session):
        self.session = session

    # --------------------------------------------------------------- proposal
    def save_proposal(self, proposal: Any) -> DemoExecutionProposalRecord:
        payload = proposal.as_dict()
        request = payload.get("request") or {}
        decision = payload.get("decision") or {}
        row = DemoExecutionProposalRecord(
            proposal_id=proposal.proposal_id, request_id=str(request.get("request_id")),
            timestamp=proposal.created_at, symbol=str(request.get("symbol") or ""),
            side=str(request.get("side") or ""), volume=float(request.get("volume") or 0.0),
            mode=str(payload.get("mode") or ""), state=str(payload.get("state")),
            approved=bool(payload.get("approved_by")), approved_by=payload.get("approved_by"),
            approved_at=payload.get("approved_at"),
            approval_reason=payload.get("approval_reason"),
            rejected_reason=payload.get("rejected_reason"),
            expires_at=payload.get("expires_at"),
            blocked_by=", ".join(decision.get("blocked_by") or []) or None,
            proposal_json=scrub(payload),
        )
        merged = self.session.merge(row)
        self.session.commit()
        return merged

    def get_proposal(self, proposal_id: str) -> DemoExecutionProposalRecord | None:
        return self.session.get(DemoExecutionProposalRecord, str(proposal_id))

    def pending_proposals(self, limit: int = 50) -> list[DemoExecutionProposalRecord]:
        return (self.session.query(DemoExecutionProposalRecord)
                .filter(DemoExecutionProposalRecord.state == "PROPOSED")
                .order_by(desc(DemoExecutionProposalRecord.timestamp)).limit(limit).all())

    def recent_proposals(self, limit: int = 50) -> list[DemoExecutionProposalRecord]:
        return (self.session.query(DemoExecutionProposalRecord)
                .order_by(desc(DemoExecutionProposalRecord.timestamp)).limit(limit).all())

    # ---------------------------------------------------------------- journal
    def save_journal(self, entry: Any) -> DemoTradeJournalRecord:
        payload = entry.as_dict()
        row = DemoTradeJournalRecord(
            trade_id=entry.trade_id, request_id=entry.request_id, timestamp=entry.timestamp,
            symbol=entry.symbol, direction=entry.direction, broker_ticket=entry.broker_ticket,
            exit_reason=entry.exit_reason, pnl=entry.pnl, gross_pnl=entry.gross_pnl,
            mae=entry.mae, mfe=entry.mfe, commission=entry.commission, swap=entry.swap,
            slippage=entry.slippage, session=entry.session, regime=entry.regime,
            model_version=entry.model_version, strategy_version=entry.strategy_version,
            feature_version=entry.feature_version, closed=entry.closed,
            opened_at=entry.opened_at, closed_at=entry.closed_at,
            journal_json=scrub(payload),
        )
        merged = self.session.merge(row)
        self.session.commit()
        return merged

    def get_journal(self, trade_id: str) -> DemoTradeJournalRecord | None:
        return self.session.get(DemoTradeJournalRecord, str(trade_id))

    def recent_journal(self, limit: int = 100, *, closed: bool | None = None):
        query = self.session.query(DemoTradeJournalRecord)
        if closed is not None:
            query = query.filter(DemoTradeJournalRecord.closed.is_(bool(closed)))
        return query.order_by(desc(DemoTradeJournalRecord.timestamp)).limit(limit).all()

    # ------------------------------------------------------------- daily risk
    def save_daily_risk(self, state: Any) -> DemoDailyRiskRecord:
        payload = state.as_dict()
        existing = (self.session.query(DemoDailyRiskRecord)
                    .filter(DemoDailyRiskRecord.trading_day == state.trading_day,
                            DemoDailyRiskRecord.timezone == state.timezone_name).one_or_none())
        row = existing or DemoDailyRiskRecord(trading_day=state.trading_day,
                                              timezone=state.timezone_name)
        row.starting_equity = state.starting_equity
        row.equity = state.equity
        row.peak_equity = state.peak_equity
        row.daily_pnl = state.daily_pnl
        row.daily_drawdown = state.daily_drawdown
        row.total_drawdown = state.total_drawdown
        row.trade_count = state.trade_count
        row.blocked = state.blocked
        row.reasons = ", ".join(state.reasons) or None
        row.updated_at = state.updated_at
        row.state_json = scrub(payload)
        self.session.add(row)
        self.session.commit()
        return row

    def latest_daily_risk(self) -> DemoDailyRiskRecord | None:
        return (self.session.query(DemoDailyRiskRecord)
                .order_by(desc(DemoDailyRiskRecord.trading_day)).first())

    def daily_risk_history(self, limit: int = 30) -> list[DemoDailyRiskRecord]:
        return (self.session.query(DemoDailyRiskRecord)
                .order_by(desc(DemoDailyRiskRecord.trading_day)).limit(limit).all())

    # --------------------------------------------------------------- position
    def save_position_snapshot(self, snapshot: Any) -> DemoPositionSnapshotRecord:
        payload = snapshot.as_dict()
        row = DemoPositionSnapshotRecord(
            ticket=snapshot.ticket, timestamp=snapshot.timestamp, symbol=snapshot.symbol,
            direction=snapshot.direction, volume=snapshot.volume,
            entry_price=snapshot.entry_price, current_price=snapshot.current_price,
            unrealized_pnl=snapshot.unrealized_pnl, mae=snapshot.mae, mfe=snapshot.mfe,
            duration_seconds=snapshot.duration_seconds, dca_levels=snapshot.dca_levels,
            snapshot_json=scrub(payload),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def recent_position_snapshots(self, limit: int = 100) -> list[DemoPositionSnapshotRecord]:
        return (self.session.query(DemoPositionSnapshotRecord)
                .order_by(desc(DemoPositionSnapshotRecord.timestamp)).limit(limit).all())

    # ------------------------------------------------------------- comparison
    def save_comparison(self, comparison: Any,
                        attribution: Any = None) -> DemoPaperComparisonRecord:
        payload = comparison.as_dict()
        if attribution is not None:
            payload["attribution"] = attribution.as_dict()
        errors = list(getattr(attribution, "errors", ())) or list(comparison.reasons)
        row = DemoPaperComparisonRecord(
            request_id=comparison.request_id, timestamp=comparison.timestamp,
            symbol=comparison.symbol, paper_entry=comparison.paper_entry,
            demo_entry=comparison.demo_entry, paper_exit=comparison.paper_exit,
            demo_exit=comparison.demo_exit, entry_difference=comparison.entry_difference,
            exit_difference=comparison.exit_difference, spread=comparison.spread,
            slippage=comparison.slippage, commission=comparison.commission,
            swap=comparison.swap, pnl_difference=comparison.pnl_difference,
            within_tolerance=comparison.within_tolerance,
            errors=", ".join(str(error) for error in errors) or None,
            comparison_json=scrub(payload),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def recent_comparisons(self, limit: int = 100) -> list[DemoPaperComparisonRecord]:
        return (self.session.query(DemoPaperComparisonRecord)
                .order_by(desc(DemoPaperComparisonRecord.timestamp)).limit(limit).all())

    # -------------------------------------------------------------- emergency
    def save_emergency_event(self, decision: Any) -> DemoEmergencyEventRecord:
        payload = decision.as_dict()
        row = DemoEmergencyEventRecord(
            timestamp=decision.timestamp,
            triggers=", ".join(str(trigger) for trigger in decision.triggers) or "UNKNOWN",
            action=decision.action, shutdown=bool(decision.shutdown),
            # Never true: the emergency path blocks new orders, it does not liquidate.
            positions_closed=False, event_json=scrub(payload),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def recent_emergency_events(self, limit: int = 50) -> list[DemoEmergencyEventRecord]:
        return (self.session.query(DemoEmergencyEventRecord)
                .order_by(desc(DemoEmergencyEventRecord.timestamp)).limit(limit).all())

    def save_kill_switch_event(self, event: Any) -> Any:
        """Delegated so the emergency path needs one repository, not two.

        The event belongs in the Phase 11 audit store next to every other
        kill-switch transition; splitting it across two tables would make the
        switch history depend on which subsystem engaged it.
        """
        from database.repositories.execution import ExecutionRepository

        return ExecutionRepository(self.session).save_kill_switch_event(event)

    # ------------------------------------------------------------- AI feedback
    def save_performance(self, record: dict[str, Any]) -> Any:
        """Section 30: closed DEMO trades feed the observation performance store.

        Delegating rather than duplicating keeps DEMO outcomes in the same table
        as forward observations, which is what makes section 32 comparable at all.
        The row is tagged `DEMO_EXECUTION` so a real fill is never silently mixed
        into a population of hypothetical observations.
        """
        from database.repositories.observation import ObservationRepository

        payload = dict(record)
        translated = {
            # The raw feedback first, then the translated names: the observation
            # store reads the translated ones and keeps the rest in record_json.
            **payload,
            "observation_id": payload.get("trade_id"),
            "cycle_id": payload.get("trade_id") or "",
            "opened_at": payload.get("timestamp"),
            "closed_at": payload.get("timestamp"),
            "symbol": payload.get("symbol"),
            "signal": payload.get("direction") or "WAIT",
            "entry": payload.get("entry_price") or 0.0,
            "exit_price": payload.get("exit_price"),
            "duration_seconds": payload.get("holding_seconds"),
            "mae": payload.get("mae"), "mfe": payload.get("mfe"),
            "hypothetical_pnl": payload.get("net_pnl"),
            "spread": payload.get("spread"), "session": payload.get("session"),
            "regime": payload.get("regime"),
            "nn_confidence": payload.get("nn_confidence"),
            "strategy_decision": payload.get("strategy_version"),
            "evidence": payload.get("evidence"),
            "demo_execution": True, "retrained": False,
        }
        return ObservationRepository(self.session).save_performance(translated)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
