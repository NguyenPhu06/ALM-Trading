"""Persistence for the Phase 13 learning pipeline.

Metadata only. Model parameters go to disk via `ModelRegistry.save_artifact`;
this repository stores where they went, never what they contain. Every payload is
scrubbed, so a credential cannot reach these tables.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from database.models import (
    DatasetAuditRecord,
    ModelDriftEventRecord,
    ModelRegistryRecord,
    ObservationPerformanceRecord,
    RetrainingRequestRecord,
)
from database.repositories.mt5 import scrub


class LearningRepository:
    def __init__(self, session: Session):
        self.session = session

    # ------------------------------------------------------------ dataset audit
    def save_dataset_audit(self, audit) -> DatasetAuditRecord:
        payload = audit.as_dict()
        row = DatasetAuditRecord(
            dataset_id=audit.dataset_id, created_at=audit.created_at,
            feature_version=audit.feature_version, label_version=audit.label_version,
            preprocessing_version=audit.preprocessing_version, horizon=audit.horizon,
            start_at=audit.start, end_at=audit.end,
            symbols=",".join(audit.symbols), timeframes=",".join(audit.timeframes),
            row_count=audit.row_count, missing_values=audit.missing_values,
            duplicate_count=audit.duplicate_count, source=audit.source,
            class_distribution=dict(audit.class_distribution), audit_json=scrub(payload),
        )
        merged = self.session.merge(row)
        self.session.commit()
        return merged

    def latest_dataset_audit(self, feature_version: str | None = None):
        query = self.session.query(DatasetAuditRecord)
        if feature_version:
            query = query.filter(DatasetAuditRecord.feature_version == feature_version)
        return query.order_by(desc(DatasetAuditRecord.created_at)).first()

    # --------------------------------------------------------------- registry
    def save_model(self, record) -> ModelRegistryRecord:
        payload = record.as_dict()
        approval = record.approval
        row = ModelRegistryRecord(
            model_id=record.model_id, model_version=record.model_version,
            task_key=record.task.key, task=record.task.task, symbol=record.task.symbol,
            timeframe=record.task.timeframe, state=str(record.state),
            feature_version=record.feature_version, label_version=record.label_version,
            training_dataset_version=record.training_dataset_version,
            preprocessing_version=record.preprocessing_version,
            training_timestamp=record.training_timestamp,
            edge_verdict=record.edge_verdict, artifact_path=record.artifact_path,
            approved_by=approval.approved_by if approval else None,
            approved_at=approval.approved_at if approval else None,
            record_json=scrub(payload),
        )
        merged = self.session.merge(row)
        self.session.commit()
        return merged

    def get_model(self, model_id: str):
        return self.session.get(ModelRegistryRecord, model_id)

    def champion(self, task_key: str):
        return (self.session.query(ModelRegistryRecord)
                .filter(ModelRegistryRecord.task_key == task_key,
                        ModelRegistryRecord.state == "CHAMPION")
                .order_by(desc(ModelRegistryRecord.training_timestamp)).first())

    def challengers(self, task_key: str, limit: int = 20):
        return (self.session.query(ModelRegistryRecord)
                .filter(ModelRegistryRecord.task_key == task_key,
                        ModelRegistryRecord.state.in_(("VALIDATED", "CANDIDATE")))
                .order_by(desc(ModelRegistryRecord.training_timestamp)).limit(limit).all())

    def recent_models(self, limit: int = 50):
        return (self.session.query(ModelRegistryRecord)
                .order_by(desc(ModelRegistryRecord.training_timestamp)).limit(limit).all())

    # ------------------------------------------------------------------ drift
    def save_drift(self, report, *, model_id: str | None = None) -> int:
        for signal in report.signals:
            self.session.add(ModelDriftEventRecord(
                timestamp=report.timestamp, model_id=model_id, kind=str(signal.kind),
                severity=str(signal.severity), metric=float(signal.metric),
                threshold=float(signal.threshold), flagged=bool(signal.flagged),
                action=signal.action, detail=signal.detail,
                event_json=scrub(signal.as_dict())))
        self.session.commit()
        return len(report.signals)

    def recent_drift(self, limit: int = 50):
        return (self.session.query(ModelDriftEventRecord)
                .order_by(desc(ModelDriftEventRecord.timestamp)).limit(limit).all())

    # ------------------------------------------------------------- retraining
    def save_retraining_request(self, request, *, model_id: str | None = None):
        payload = request.as_dict()
        row = RetrainingRequestRecord(
            request_id=request.request_id, created_at=request.created_at,
            state=str(request.state),
            triggers=",".join(str(item) for item in request.triggers),
            reasons=", ".join(request.reasons) if request.reasons else None,
            approved_by=request.approved_by, model_id=model_id,
            request_json=scrub(payload))
        merged = self.session.merge(row)
        self.session.commit()
        return merged

    def recent_retraining_requests(self, limit: int = 50):
        return (self.session.query(RetrainingRequestRecord)
                .order_by(desc(RetrainingRequestRecord.created_at)).limit(limit).all())

    # -------------------------------------------------- observation performance
    def attach_label(self, observation_id: str, label, *, future_price: float | None = None):
        """Write the resolved forward outcome onto an existing observation row."""
        row = (self.session.query(ObservationPerformanceRecord)
               .filter(ObservationPerformanceRecord.observation_id == observation_id).first())
        if row is None:
            return None
        row.future_price = float(future_price if future_price is not None else label.future_price)
        row.future_return = float(label.future_return)
        row.mfe = float(label.future_mfe)
        row.mae = float(label.future_mae)
        row.hypothetical_pnl = float(label.net_return)
        row.horizon = label.horizon
        row.label_version = label.label_version
        self.session.commit()
        return row

    def dataset_row_exists(self, observation_id: str) -> bool:
        """Phase 14 duplicate check: has this observation already been labelled?"""
        return (self.session.query(ObservationPerformanceRecord)
                .filter(ObservationPerformanceRecord.observation_id == observation_id,
                        ObservationPerformanceRecord.future_return.isnot(None))
                .first() is not None)

    def unlabelled_observations(self, limit: int = 500):
        return (self.session.query(ObservationPerformanceRecord)
                .filter(ObservationPerformanceRecord.future_return.is_(None))
                .order_by(ObservationPerformanceRecord.opened_at).limit(limit).all())

    def labelled_count(self) -> int:
        return (self.session.query(ObservationPerformanceRecord)
                .filter(ObservationPerformanceRecord.future_return.isnot(None)).count())
