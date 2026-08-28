"""Persistence for Phase 17 shadow trading and DEMO validation.

Every payload passes through `scrub()` before it is written, so a credential
cannot reach these tables even if a caller puts one in a context dict.

Two columns are written as constants on purpose. `shadow_signals.orders_sent` is
always 0 and `circuit_breaker_events.positions_closed` is always False: both are
invariants, and writing them from the record rather than pinning them here would
mean a bug upstream could quietly record the opposite.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    CircuitBreakerEventRecord,
    ExecutionQualityRecord,
    PerformanceGateRecord,
    ShadowDemoComparisonRecord,
    ShadowOutcomeRecord,
    ShadowSignalRecord,
    ValidationRunRecord,
)
from database.repositories.mt5 import scrub


class ValidationRepository:
    def __init__(self, session: Session):
        self.session = session

    # ----------------------------------------------------------------- shadow
    def save_shadow_signal(self, signal: Any) -> ShadowSignalRecord:
        payload = signal.as_dict()
        row = ShadowSignalRecord(
            shadow_signal_id=signal.shadow_signal_id,
            demo_execution_request_id=signal.demo_execution_request_id,
            timestamp=signal.timestamp, symbol=signal.symbol, side=signal.side,
            entry=signal.entry, stop_loss=signal.stop_loss, take_profit=signal.take_profit,
            volume=signal.volume, strategy=signal.strategy,
            strategy_version=signal.strategy_version, model_version=signal.model_version,
            feature_version=signal.feature_version, confidence=signal.confidence,
            risk_snapshot_id=signal.risk_snapshot_id, risk_state=signal.risk_state,
            session=signal.session, regime=signal.regime, timeframe=signal.timeframe,
            signal_timeframe=signal.signal_timeframe, spread=signal.spread,
            approved=signal.approved, decision_approved=signal.decision_approved,
            executed=signal.executed,
            not_executed_reason=signal.not_executed_reason,
            blocked_reasons=", ".join(signal.blocked_reasons) or None,
            status=str(signal.status),
            # Pinned, not copied: a shadow signal has no transport.
            orders_sent=0, signal_json=scrub(payload),
        )
        merged = self.session.merge(row)
        self.session.commit()
        return merged

    def save_shadow_outcome(self, signal: Any, outcome: Any) -> ShadowOutcomeRecord:
        row = ShadowOutcomeRecord(
            shadow_signal_id=outcome.shadow_signal_id, symbol=outcome.symbol,
            side=outcome.side, resolved_at=outcome.resolved_at,
            expected_entry=outcome.expected_entry, expected_exit=outcome.expected_exit,
            expected_pnl=outcome.expected_pnl, mfe=outcome.mfe, mae=outcome.mae,
            duration_seconds=outcome.duration_seconds, spread=outcome.spread,
            slippage_estimate=outcome.slippage_estimate,
            commission_estimate=outcome.commission_estimate,
            net_expected_pnl=outcome.net_expected_pnl, exit_reason=outcome.exit_reason,
            executed=bool(getattr(signal, "executed", False)),
            session=getattr(signal, "session", None), regime=getattr(signal, "regime", None),
            outcome_json=scrub(outcome.as_dict()),
        )
        merged = self.session.merge(row)
        # The signal's status changed to RESOLVED; keep the two rows consistent.
        self.save_shadow_signal(signal)
        self.session.commit()
        return merged

    def get_shadow_signal(self, shadow_id: str) -> ShadowSignalRecord | None:
        return self.session.get(ShadowSignalRecord, str(shadow_id))

    def recent_shadow_signals(self, limit: int = 200, *, executed: bool | None = None):
        query = self.session.query(ShadowSignalRecord)
        if executed is not None:
            query = query.filter(ShadowSignalRecord.executed.is_(bool(executed)))
        return query.order_by(desc(ShadowSignalRecord.timestamp)).limit(limit).all()

    def recent_shadow_outcomes(self, limit: int = 500) -> list[ShadowOutcomeRecord]:
        return (self.session.query(ShadowOutcomeRecord)
                .order_by(desc(ShadowOutcomeRecord.resolved_at)).limit(limit).all())

    # ------------------------------------------------------------- comparison
    def save_comparison(self, comparison: Any) -> ShadowDemoComparisonRecord:
        row = ShadowDemoComparisonRecord(
            shadow_signal_id=comparison.shadow_signal_id,
            demo_execution_request_id=comparison.demo_execution_request_id,
            timestamp=comparison.timestamp, symbol=comparison.symbol,
            signal_difference=comparison.signal_difference,
            entry_difference=comparison.entry_difference,
            exit_difference=comparison.exit_difference,
            slippage_difference=comparison.slippage_difference,
            cost_difference=comparison.cost_difference,
            pnl_difference=comparison.pnl_difference,
            mae_difference=comparison.mae_difference,
            mfe_difference=comparison.mfe_difference,
            time_difference=comparison.time_difference,
            primary_kind=str(comparison.primary),
            kinds=", ".join(str(kind) for kind in comparison.kinds) or None,
            matched=comparison.matched, shadow_net_pnl=comparison.shadow_net_pnl,
            demo_net_pnl=comparison.demo_net_pnl,
            comparison_json=scrub(comparison.as_dict()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def recent_comparisons(self, limit: int = 200) -> list[ShadowDemoComparisonRecord]:
        return (self.session.query(ShadowDemoComparisonRecord)
                .order_by(desc(ShadowDemoComparisonRecord.timestamp)).limit(limit).all())

    # ------------------------------------------------------ execution quality
    def save_execution_quality(self, quality: Any, *, window: str = "ALL"
                               ) -> ExecutionQualityRecord:
        row = ExecutionQualityRecord(
            timestamp=quality.timestamp, window=str(window), submitted=quality.submitted,
            filled=quality.filled, rejected=quality.rejected, errored=quality.errored,
            fill_rate=quality.fill_rate, rejection_rate=quality.rejection_rate,
            average_slippage=quality.average_slippage, worst_slippage=quality.worst_slippage,
            reconciliation_failures=quality.reconciliation_failures,
            connection_failures=quality.connection_failures, reliable=quality.reliable,
            quality_json=scrub(quality.as_dict()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def recent_execution_quality(self, limit: int = 50) -> list[ExecutionQualityRecord]:
        return (self.session.query(ExecutionQualityRecord)
                .order_by(desc(ExecutionQualityRecord.timestamp)).limit(limit).all())

    # ------------------------------------------------------------------ runs
    def save_validation_run(self, run_id: str, kind: str, report: Any, *,
                            window: str | None = None, samples: int = 0,
                            edge_status: str = "INSUFFICIENT_DATA",
                            passed: bool = False) -> ValidationRunRecord:
        payload = report.as_dict() if hasattr(report, "as_dict") else dict(report or {})
        row = ValidationRunRecord(
            run_id=str(run_id), timestamp=datetime.now(timezone.utc), kind=str(kind),
            window=window, samples=int(samples), edge_status=str(edge_status),
            passed=bool(passed),
            reasons=", ".join(str(reason) for reason in payload.get("reasons", [])) or None,
            report_json=scrub(payload),
        )
        merged = self.session.merge(row)
        self.session.commit()
        return merged

    def recent_runs(self, limit: int = 50, *, kind: str | None = None):
        query = self.session.query(ValidationRunRecord)
        if kind:
            query = query.filter(ValidationRunRecord.kind == str(kind))
        return query.order_by(desc(ValidationRunRecord.timestamp)).limit(limit).all()

    # ------------------------------------------------------------------ gates
    def save_gate_report(self, report: Any, *, run_id: str | None = None
                         ) -> list[PerformanceGateRecord]:
        rows: list[PerformanceGateRecord] = []
        for gate in report.gates:
            row = PerformanceGateRecord(
                timestamp=report.timestamp, run_id=run_id, gate=gate.name,
                status=str(gate.status),
                observed=_float(gate.observed), threshold=_float(gate.threshold),
                detail=gate.detail,
                # Pinned: passing a gate is evidence, never an action.
                enabled_execution=False, gate_json=scrub(gate.as_dict()),
            )
            self.session.add(row)
            rows.append(row)
        self.session.commit()
        return rows

    def recent_gates(self, limit: int = 100) -> list[PerformanceGateRecord]:
        return (self.session.query(PerformanceGateRecord)
                .order_by(desc(PerformanceGateRecord.timestamp)).limit(limit).all())

    # -------------------------------------------------------- circuit breaker
    def save_breaker_event(self, event: Any) -> CircuitBreakerEventRecord:
        checklist = event.checklist
        row = CircuitBreakerEventRecord(
            timestamp=event.timestamp, state=str(event.state),
            triggers=", ".join(str(trigger) for trigger in event.triggers) or None,
            reasons=", ".join(event.reasons) or None, actor=event.actor,
            # Pinned: the breaker blocks new orders, it never liquidates.
            positions_closed=False,
            health_check=bool(checklist.health_check) if checklist else False,
            risk_check=bool(checklist.risk_check) if checklist else False,
            account_validation=bool(checklist.account_validation) if checklist else False,
            human_approval=bool(checklist.human_approval) if checklist else False,
            event_json=scrub(event.as_dict()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def recent_breaker_events(self, limit: int = 50) -> list[CircuitBreakerEventRecord]:
        return (self.session.query(CircuitBreakerEventRecord)
                .order_by(desc(CircuitBreakerEventRecord.timestamp)).limit(limit).all())


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
