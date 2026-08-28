"""Persistence for the Phase 14 forward observation loop.

Two properties matter more than anything else here:

* **Idempotency.** `save_observation` upserts on the deterministic observation id
  and `observation_exists` answers the driver's duplicate check, so a restart
  re-reads its own history instead of writing a second copy (section 27).
* **No secrets.** Every JSON payload passes through `scrub()`, the same helper
  the MT5 and observation repositories use.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import uuid4

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from database.models import (
    EdgeEvaluationRecord,
    ModelErrorRecord,
    ModelPerformanceRecord,
    ObservationOutcomeRecord,
    ObservationRecord,
    TrainingRunRecord,
)
from database.repositories.mt5 import scrub


class ForwardObservationRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------ observations
    def save_observation(self, observation: Any) -> ObservationRecord:
        """Upsert by observation id: the lifecycle advances one record, not many."""
        payload = observation.as_dict()
        row = self.session.get(ObservationRecord, observation.observation_id)
        values = {
            "cycle_id": observation.cycle_id, "symbol": observation.symbol.upper(),
            "timestamp": observation.timestamp, "timeframe": observation.timeframe,
            "entry_price": _number(observation.entry_price),
            "direction": str(observation.direction),
            "strategy": observation.strategy, "market_regime": observation.market_regime,
            "session": observation.session, "feature_version": observation.feature_version,
            "model_version": observation.model_version,
            "nn_confidence": _number(observation.nn_confidence),
            "risk_state": observation.risk_state,
            "observation_horizon": observation.observation_horizon,
            "status": str(observation.status), "deadline": observation.deadline,
            "failure_reason": observation.failure_reason,
            "updated_at": observation.updated_at or _utcnow(),
            "observation_json": scrub(payload),
        }
        if row is None:
            row = ObservationRecord(observation_id=observation.observation_id,
                                    created_at=observation.created_at or _utcnow(), **values)
            self.session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        self.session.commit()
        return row

    def observation_exists(self, *, cycle_id: str | None = None,
                           observation_id: str | None = None) -> bool:
        if observation_id is not None:
            return self.session.get(ObservationRecord, observation_id) is not None
        if cycle_id is None:
            return False
        stmt = select(ObservationRecord.observation_id).where(
            ObservationRecord.cycle_id == cycle_id)
        return self.session.execute(stmt).first() is not None

    def known_cycle_ids(self, limit: int = 5000) -> list[str]:
        stmt = (select(ObservationRecord.cycle_id)
                .order_by(desc(ObservationRecord.timestamp)).limit(limit))
        return [row[0] for row in self.session.execute(stmt).all()]

    def get_observation(self, observation_id: str) -> ObservationRecord | None:
        return self.session.get(ObservationRecord, observation_id)

    def observations_due(self, *, now: datetime, limit: int = 200,
                         status: str = "OBSERVING") -> list[Any]:
        """Observations whose horizon has elapsed and which are still open."""
        rows = (self.session.query(ObservationRecord)
                .filter(ObservationRecord.status == status,
                        ObservationRecord.deadline.isnot(None),
                        ObservationRecord.deadline <= now)
                .order_by(ObservationRecord.deadline).limit(limit).all())
        return [self.to_observation(row) for row in rows]

    def recent_observations(self, limit: int = 100) -> list[ObservationRecord]:
        return (self.session.query(ObservationRecord)
                .order_by(desc(ObservationRecord.timestamp)).limit(limit).all())

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.session.query(ObservationRecord.status).all():
            counts[row[0]] = counts.get(row[0], 0) + 1
        return counts

    @staticmethod
    def to_observation(row: ObservationRecord) -> Any:
        """Rebuild the domain object the driver works with.

        Timestamps are re-attached to UTC on the way out: SQLite hands back naive
        datetimes even for `DateTime(timezone=True)` columns, and an observation
        reloaded after a restart would then raise when its deadline is compared
        against an aware `now`.
        """
        from observation.lifecycle import Observation, ObservationStatus

        payload = dict(row.observation_json or {})
        return Observation(
            observation_id=row.observation_id, cycle_id=row.cycle_id, symbol=row.symbol,
            timestamp=_aware(row.timestamp), entry_price=row.entry_price,
            direction=row.direction,
            strategy=row.strategy, market_regime=row.market_regime, session=row.session,
            feature_version=row.feature_version, model_version=row.model_version,
            nn_prediction=payload.get("nn_prediction"), nn_confidence=row.nn_confidence,
            risk_state=row.risk_state, observation_horizon=row.observation_horizon,
            status=ObservationStatus(row.status), timeframe=row.timeframe,
            created_at=_aware(row.created_at), updated_at=_aware(row.updated_at),
            failure_reason=row.failure_reason,
            context=dict(payload.get("context") or {}))

    # ---------------------------------------------------------------- outcomes
    def save_outcome(self, observation: Any, outcome: Any) -> ObservationOutcomeRecord:
        payload = outcome.as_dict()
        label = payload.get("label") or {}
        row = self.session.get(ObservationOutcomeRecord, outcome.observation_id)
        values = {
            "symbol": outcome.symbol, "horizon": outcome.horizon,
            "direction": outcome.direction, "entry_price": float(outcome.entry_price),
            "future_price": float(outcome.future_price),
            "future_return": float(outcome.future_return),
            "mfe": _number(outcome.mfe), "mae": _number(outcome.mae),
            "hypothetical_pnl": _number(outcome.hypothetical_pnl),
            "net_hypothetical_pnl": float(outcome.net_hypothetical_pnl),
            "estimated_cost": _number(outcome.estimated_cost),
            "spread": _number(outcome.spread),
            "holding_time": _number(outcome.holding_time),
            "resolved_at": outcome.resolved_at,
            "regime": getattr(observation, "market_regime", None),
            "session": getattr(observation, "session", None),
            "timeframe": getattr(observation, "timeframe", None),
            "label_version": label.get("label_version"),
            "evidence": str(outcome.evidence),
            "outcome_json": scrub(payload),
        }
        if row is None:
            row = ObservationOutcomeRecord(observation_id=outcome.observation_id, **values)
            self.session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        self.session.commit()
        return row

    def outcome_exists(self, observation_id: str) -> bool:
        return self.session.get(ObservationOutcomeRecord, observation_id) is not None

    # `DatasetIngestor` calls this name for its duplicate check.
    def dataset_row_exists(self, observation_id: str) -> bool:
        return self.outcome_exists(observation_id)

    def recent_outcomes(self, limit: int = 500) -> list[ObservationOutcomeRecord]:
        return (self.session.query(ObservationOutcomeRecord)
                .order_by(desc(ObservationOutcomeRecord.resolved_at)).limit(limit).all())

    def outcomes_since(self, since: datetime,
                       limit: int = 5000) -> list[ObservationOutcomeRecord]:
        return (self.session.query(ObservationOutcomeRecord)
                .filter(ObservationOutcomeRecord.resolved_at >= since)
                .order_by(ObservationOutcomeRecord.resolved_at).limit(limit).all())

    # ------------------------------------------------------------------ errors
    def save_error(self, analysis: Any, *, model_id: str | None = None,
                   timestamp: datetime | None = None) -> ModelErrorRecord:
        payload = analysis.as_dict()
        row = ModelErrorRecord(
            observation_id=analysis.observation_id, model_id=model_id,
            timestamp=timestamp or _utcnow(), predicted=analysis.predicted,
            actual=analysis.actual or "UNKNOWN", confidence=_number(analysis.confidence),
            error_class=str(analysis.primary),
            tags=", ".join(str(tag) for tag in analysis.tags) or None,
            high_confidence_failure=bool(analysis.high_confidence_failure),
            net_pnl=_number(analysis.net_pnl), regime=analysis.regime,
            session=analysis.session, error_json=scrub(payload))
        self.session.add(row)
        self.session.commit()
        return row

    def recent_errors(self, limit: int = 200,
                      high_confidence_only: bool = False) -> list[ModelErrorRecord]:
        query = self.session.query(ModelErrorRecord)
        if high_confidence_only:
            query = query.filter(ModelErrorRecord.high_confidence_failure.is_(True))
        return query.order_by(desc(ModelErrorRecord.timestamp)).limit(limit).all()

    # ------------------------------------------------------------- performance
    def save_performance(self, window: str, metrics: Any, *, model_id: str | None = None,
                         model_version: str | None = None,
                         calculated_at: datetime | None = None) -> ModelPerformanceRecord:
        payload = metrics.as_dict() if hasattr(metrics, "as_dict") else dict(metrics)
        calibration = payload.get("calibration") or {}
        row = ModelPerformanceRecord(
            model_id=model_id, model_version=model_version, window=str(window),
            calculated_at=calculated_at or _utcnow(),
            samples=int(payload.get("samples", 0) or 0),
            reliable=bool(payload.get("reliable", False)),
            win_rate=_number(payload.get("win_rate")),
            expectancy=_number(payload.get("expectancy")),
            profit_factor=_number(payload.get("profit_factor")),
            net_pnl=_number(payload.get("net_pnl")),
            max_drawdown=_number(payload.get("max_drawdown")),
            average_mae=_number(payload.get("average_mae")),
            average_mfe=_number(payload.get("average_mfe")),
            prediction_accuracy=_number(payload.get("prediction_accuracy")),
            brier_score=_number(calibration.get("brier_score")),
            metrics_json=scrub(payload))
        self.session.add(row)
        self.session.commit()
        return row

    def recent_performance(self, limit: int = 50) -> list[ModelPerformanceRecord]:
        return (self.session.query(ModelPerformanceRecord)
                .order_by(desc(ModelPerformanceRecord.calculated_at)).limit(limit).all())

    # -------------------------------------------------------------------- edge
    def save_edge(self, report: Any, *, model_id: str | None = None,
                  symbol: str | None = None,
                  timestamp: datetime | None = None) -> EdgeEvaluationRecord:
        payload = report.as_dict() if hasattr(report, "as_dict") else dict(report)
        metrics = payload.get("metrics") or {}
        row = EdgeEvaluationRecord(
            evaluation_id=uuid4().hex, model_id=model_id, symbol=symbol,
            timestamp=timestamp or _utcnow(), verdict=str(payload.get("verdict")),
            samples=int(payload.get("samples", 0) or 0),
            expectancy=_number(metrics.get("expectancy")),
            win_rate=_number(metrics.get("win_rate")),
            profit_factor=_number(metrics.get("profit_factor")),
            net_pnl=_number(metrics.get("net_pnl")),
            max_drawdown=_number(metrics.get("max_drawdown")),
            beats_baselines=not payload.get("not_beaten"),
            reasons=", ".join(str(reason) for reason in payload.get("reasons", [])) or None,
            evidence=str(payload.get("evidence") or "FORWARD_OBSERVATION"),
            report_json=scrub(payload))
        self.session.add(row)
        self.session.commit()
        return row

    def latest_edge(self, symbol: str | None = None) -> EdgeEvaluationRecord | None:
        query = self.session.query(EdgeEvaluationRecord)
        if symbol:
            query = query.filter(EdgeEvaluationRecord.symbol == symbol.upper())
        return query.order_by(desc(EdgeEvaluationRecord.timestamp)).first()

    def recent_edge(self, limit: int = 20) -> list[EdgeEvaluationRecord]:
        return (self.session.query(EdgeEvaluationRecord)
                .order_by(desc(EdgeEvaluationRecord.timestamp)).limit(limit).all())

    # ----------------------------------------------------------- training runs
    def save_training_run(self, report: Any, *, run_id: str | None = None,
                          trigger: str | None = None, requested_by: str | None = None,
                          started_at: datetime | None = None,
                          finished_at: datetime | None = None) -> TrainingRunRecord:
        payload = report.as_dict() if hasattr(report, "as_dict") else dict(report)
        job = payload.get("job") or {}
        row = TrainingRunRecord(
            run_id=run_id or uuid4().hex, model_id=payload.get("model_id"),
            started_at=started_at or _parse(job.get("started_at")) or _utcnow(),
            finished_at=finished_at or _parse(job.get("finished_at")),
            dataset_id=payload.get("dataset_id"), trigger=trigger,
            requested_by=requested_by, ok=bool(payload.get("ok")),
            failed_step=payload.get("failed_step"), state=payload.get("state"),
            edge_verdict=((payload.get("evaluation") or {}).get("edge_verdict")),
            registered=bool(payload.get("registered")),
            # Never anything but False; the column records the guarantee.
            promoted=False, error=job.get("error"), run_json=scrub(payload))
        self.session.add(row)
        self.session.commit()
        return row

    def recent_training_runs(self, limit: int = 20) -> list[TrainingRunRecord]:
        return (self.session.query(TrainingRunRecord)
                .order_by(desc(TrainingRunRecord.started_at)).limit(limit).all())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """Naive timestamps from the database are UTC; say so explicitly."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def observation_entries(outcomes: Sequence[ObservationOutcomeRecord]) -> list[dict[str, Any]]:
    """Rows shaped for the edge detector and the segment learners."""
    return [{"observation_id": row.observation_id,
             "net_hypothetical_pnl": row.net_hypothetical_pnl,
             "resolved_at": row.resolved_at, "regime": row.regime,
             "session": row.session, "timeframe": row.timeframe,
             "mae": row.mae, "mfe": row.mfe, "spread": row.spread}
            for row in outcomes]
