"""Persistence for the Phase 11 DEMO execution audit trail.

Every payload passes through `scrub()` before it is written, so a credential
cannot reach these tables even if a caller puts one in a context dict.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    ExecutionAuditLogRecord,
    ExecutionRequestRecord,
    ExecutionResultRecord,
    KillSwitchEventRecord,
    ReconciliationRecordRow,
)
from database.repositories.mt5 import scrub


class ExecutionRepository:
    def __init__(self, session: Session):
        self.session = session

    # ----------------------------------------------------------------- request
    def save_request(self, request, *, environment: str = "DEMO") -> ExecutionRequestRecord:
        payload = request.as_dict()
        row = ExecutionRequestRecord(
            request_id=request.request_id, timestamp=request.timestamp, symbol=request.symbol,
            side=str(request.side), order_type=str(request.order_type), volume=request.volume,
            price=request.price, sl=request.sl, tp=request.tp, intent=str(request.intent),
            strategy_id=request.strategy_id, signal_id=request.signal_id,
            comment=request.comment, environment=environment, request_json=scrub(payload),
        )
        merged = self.session.merge(row)
        self.session.commit()
        return merged

    # ------------------------------------------------------------------ result
    def save_result(self, result) -> ExecutionResultRecord:
        row = ExecutionResultRecord(
            request_id=result.request_id, timestamp=result.timestamp, status=str(result.status),
            broker_ticket=result.broker_ticket, symbol=result.symbol, side=result.side,
            requested_volume=result.requested_volume, filled_volume=result.filled_volume,
            requested_price=result.requested_price, filled_price=result.filled_price,
            sl=result.sl, tp=result.tp, error_code=result.error_code,
            error_message=result.error_message, environment=result.environment,
            result_json=scrub(result.as_dict()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    # ------------------------------------------------------------------- audit
    def save_audit(self, request_id: str, stage: str, payload: Any, *, approved: bool | None = None,
                   reasons: Any = (), actor: str = "system",
                   environment: str = "DEMO") -> ExecutionAuditLogRecord:
        codes = [str(reason) for reason in (reasons or ())]
        row = ExecutionAuditLogRecord(
            request_id=request_id, timestamp=datetime.now(timezone.utc), stage=stage,
            approved=approved, reasons=", ".join(codes) or None, actor=actor,
            environment=environment, payload_json=scrub(payload),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def audit_trail(self, request_id: str) -> list[ExecutionAuditLogRecord]:
        return (self.session.query(ExecutionAuditLogRecord)
                .filter(ExecutionAuditLogRecord.request_id == request_id)
                .order_by(ExecutionAuditLogRecord.id).all())

    def recent_audit(self, limit: int = 100) -> list[ExecutionAuditLogRecord]:
        return (self.session.query(ExecutionAuditLogRecord)
                .order_by(desc(ExecutionAuditLogRecord.timestamp)).limit(limit).all())

    # --------------------------------------------------------- reconciliation
    def save_reconciliation(self, record) -> ReconciliationRecordRow:
        row = ReconciliationRecordRow(
            request_id=record.request_id, timestamp=record.timestamp, status=str(record.status),
            broker_ticket=record.broker_ticket, symbol=record.symbol,
            reasons=", ".join(record.reasons) if record.reasons else None,
            record_json=scrub(record.as_dict()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def latest_reconciliation(self) -> ReconciliationRecordRow | None:
        return (self.session.query(ReconciliationRecordRow)
                .order_by(desc(ReconciliationRecordRow.timestamp)).first())

    # ------------------------------------------------------------ kill switch
    def save_kill_switch_event(self, event) -> KillSwitchEventRecord:
        row = KillSwitchEventRecord(
            timestamp=event.timestamp, state=str(event.state), engaged=event.engaged,
            reason=event.reason, actor=event.actor, event_json=scrub(event.as_dict()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def recent_kill_switch_events(self, limit: int = 50) -> list[KillSwitchEventRecord]:
        return (self.session.query(KillSwitchEventRecord)
                .order_by(desc(KillSwitchEventRecord.timestamp)).limit(limit).all())

    # ------------------------------------------------------------------ latest
    def latest_request(self) -> ExecutionRequestRecord | None:
        return (self.session.query(ExecutionRequestRecord)
                .order_by(desc(ExecutionRequestRecord.timestamp)).first())

    def latest_result(self) -> ExecutionResultRecord | None:
        return (self.session.query(ExecutionResultRecord)
                .order_by(desc(ExecutionResultRecord.timestamp)).first())

    def results_for(self, request_id: str) -> list[ExecutionResultRecord]:
        return (self.session.query(ExecutionResultRecord)
                .filter(ExecutionResultRecord.request_id == request_id)
                .order_by(ExecutionResultRecord.id).all())
