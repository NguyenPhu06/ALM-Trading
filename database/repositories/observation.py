"""Persistence for Phase 12 observation cycles.

Every payload passes through `scrub()`, so a credential cannot land here even if
a caller puts one in a context dict.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    ExecutionSimulationRecord,
    FeatureSnapshotRecord,
    MT5HealthEventRecord,
    ObservationMarketSnapshotRecord,
    ObservationPerformanceRecord,
    SystemHealthRecord,
)
from database.repositories.mt5 import scrub


class ObservationRepository:
    def __init__(self, session: Session):
        self.session = session

    # ---------------------------------------------------------------- snapshots
    def save_market_snapshot(self, snapshot, *, regime: str | None = None,
                             session_name: str | None = None) -> ObservationMarketSnapshotRecord:
        payload = snapshot.as_dict()
        price = payload.get("price") or {}
        spread = payload.get("spread") or {}
        row = ObservationMarketSnapshotRecord(
            cycle_id=snapshot.cycle_id or "", timestamp=snapshot.timestamp,
            symbol=snapshot.symbol, regime=regime, session=session_name,
            mid_price=_number(price.get("mid_price")), spread=_number(spread.get("spread")),
            source=snapshot.source, snapshot_json=scrub(payload),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def save_feature_snapshot(self, snapshot, *, signal: str | None = None) -> FeatureSnapshotRecord:
        payload = snapshot.as_dict()
        regime = (payload.get("regime") or {}).get("regime")
        row = FeatureSnapshotRecord(
            cycle_id=snapshot.cycle_id, timestamp=snapshot.timestamp, symbol=snapshot.symbol,
            regime=regime, signal=signal, feature_version=snapshot.feature_version,
            source=snapshot.source, snapshot_json=scrub(payload),
        )
        self.session.add(row)
        self.session.commit()
        return row

    # -------------------------------------------------------------- simulation
    def save_simulation(self, simulation, *, cycle_id: str | None = None) -> ExecutionSimulationRecord:
        payload = simulation.as_dict()
        row = ExecutionSimulationRecord(
            simulation_id=simulation.simulation_id, cycle_id=cycle_id,
            timestamp=simulation.timestamp, symbol=simulation.symbol,
            signal=str(simulation.signal), risk=str(simulation.risk),
            execution=str(simulation.execution), reason=simulation.primary_reason,
            confidence=float(simulation.confidence),
            observation_mode=bool(simulation.observation_mode),
            orders_sent=0, simulation_json=scrub(payload),
        )
        self.session.add(row)
        self.session.commit()
        return row

    # ------------------------------------------------------------------ health
    def save_health(self, health, *, cycle_id: str | None = None) -> SystemHealthRecord:
        row = SystemHealthRecord(
            timestamp=health.timestamp, state=str(health.state), cycle_id=cycle_id,
            last_error=health.last_error, health_json=scrub(health.as_dict()),
        )
        self.session.add(row)
        self.session.commit()
        return row

    def save_mt5_health_event(self, result) -> MT5HealthEventRecord:
        payload = result.as_dict()
        account = payload.get("account") or {}
        terminal = payload.get("terminal") or {}
        row = MT5HealthEventRecord(
            timestamp=result.timestamp, status=str(result.status),
            login_masked=account.get("login"), broker=account.get("broker"),
            server=account.get("server"), account_type=account.get("account_type"),
            terminal_build=terminal.get("build"),
            reasons=", ".join(result.reasons) if result.reasons else None,
            event_json=scrub(payload),
        )
        self.session.add(row)
        self.session.commit()
        return row

    # ------------------------------------------------------------- performance
    def save_performance(self, record: dict[str, Any]) -> ObservationPerformanceRecord:
        row = ObservationPerformanceRecord(
            observation_id=record.get("observation_id"),
            cycle_id=str(record.get("cycle_id") or ""),
            opened_at=record.get("opened_at") or datetime.now(timezone.utc),
            closed_at=record.get("closed_at"), symbol=str(record.get("symbol") or ""),
            signal=str(record.get("signal") or "WAIT"), entry=float(record.get("entry") or 0.0),
            exit_price=_number(record.get("exit_price")),
            duration_seconds=_number(record.get("duration_seconds")),
            mae=_number(record.get("mae")), mfe=_number(record.get("mfe")),
            hypothetical_pnl=_number(record.get("hypothetical_pnl")),
            spread=_number(record.get("spread")), session=record.get("session"),
            regime=record.get("regime"), nn_confidence=_number(record.get("nn_confidence")),
            strategy_confidence=_number(record.get("strategy_confidence")),
            dca_state=record.get("dca_state"),
            nn_probability=_number(record.get("nn_probability")),
            strategy_decision=record.get("strategy_decision"),
            observed=True, record_json=scrub(record),
        )
        self.session.add(row)
        self.session.commit()
        return row

    # ------------------------------------------------------------------ cycle
    def save_cycle(self, feature_snapshot, market_snapshot, simulation, health) -> None:
        """Called by ObservationCycle: one call persists the whole cycle."""
        regime = (feature_snapshot.regime or {}).get("regime")
        session_name = (feature_snapshot.session or {}).get("session")
        self.save_feature_snapshot(feature_snapshot, signal=str(simulation.signal))
        self.save_market_snapshot(market_snapshot, regime=regime, session_name=session_name)
        self.save_simulation(simulation, cycle_id=feature_snapshot.cycle_id)
        self.save_health(health, cycle_id=feature_snapshot.cycle_id)

    # ------------------------------------------------------------------ reads
    def latest_market_snapshot(self, symbol: str | None = None):
        query = self.session.query(ObservationMarketSnapshotRecord)
        if symbol:
            query = query.filter(ObservationMarketSnapshotRecord.symbol == symbol.upper())
        return query.order_by(desc(ObservationMarketSnapshotRecord.timestamp)).first()

    def latest_feature_snapshot(self, symbol: str | None = None):
        query = self.session.query(FeatureSnapshotRecord)
        if symbol:
            query = query.filter(FeatureSnapshotRecord.symbol == symbol.upper())
        return query.order_by(desc(FeatureSnapshotRecord.timestamp)).first()

    def latest_health(self):
        return (self.session.query(SystemHealthRecord)
                .order_by(desc(SystemHealthRecord.timestamp)).first())

    def recent_simulations(self, limit: int = 50):
        return (self.session.query(ExecutionSimulationRecord)
                .order_by(desc(ExecutionSimulationRecord.timestamp)).limit(limit).all())

    def recent_performance(self, limit: int = 100):
        return (self.session.query(ObservationPerformanceRecord)
                .order_by(desc(ObservationPerformanceRecord.opened_at)).limit(limit).all())

    def recent_mt5_health(self, limit: int = 50):
        return (self.session.query(MT5HealthEventRecord)
                .order_by(desc(MT5HealthEventRecord.timestamp)).limit(limit).all())


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
