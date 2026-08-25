from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import DatasetMetadataRecord, MarketFeature, MarketLabel

if TYPE_CHECKING:
    from ai.datasets.pipeline import MLDatasetArtifact


class MLDatasetRepository:
    """Persist immutable versioned Phase 4 artifacts without duplicating candles."""

    def __init__(self, session: Session):
        self.session = session

    def persist(self, artifact: MLDatasetArtifact) -> dict[str, int]:
        inserted_features = inserted_labels = 0
        try:
            existing_metadata = self.session.get(DatasetMetadataRecord, artifact.metadata.dataset_id)
            if existing_metadata:
                if existing_metadata.dataset_hash != artifact.metadata.dataset_hash:
                    raise ValueError("dataset_id already exists with different immutable content")
                return {"features": 0, "labels": 0, "metadata": 0}
            for sample in artifact.samples:
                feature = self.session.scalar(select(MarketFeature).where(
                    MarketFeature.symbol == sample.symbol,
                    MarketFeature.base_timeframe == artifact.metadata.base_timeframe,
                    MarketFeature.timestamp == sample.timestamp,
                    MarketFeature.feature_version == artifact.metadata.feature_version,
                ))
                if feature is None:
                    self.session.add(MarketFeature(
                        timestamp=sample.timestamp, symbol=sample.symbol,
                        base_timeframe=artifact.metadata.base_timeframe,
                        feature_version=artifact.metadata.feature_version,
                        features_json=sample.features, schema_hash=artifact.metadata.schema_hash,
                    ))
                    inserted_features += 1
                elif feature.features_json != sample.features or feature.schema_hash != artifact.metadata.schema_hash:
                    raise ValueError("immutable market feature conflicts with existing version")
                label_payload = self._jsonable(asdict(sample.label))
                label = self.session.scalar(select(MarketLabel).where(
                    MarketLabel.symbol == sample.symbol,
                    MarketLabel.base_timeframe == artifact.metadata.base_timeframe,
                    MarketLabel.timestamp == sample.timestamp,
                    MarketLabel.label_version == artifact.metadata.label_version,
                ))
                if label is None:
                    self.session.add(MarketLabel(
                        timestamp=sample.timestamp, label_end_timestamp=sample.label.label_end_timestamp,
                        symbol=sample.symbol, base_timeframe=artifact.metadata.base_timeframe,
                        label_version=artifact.metadata.label_version, labels_json=label_payload,
                    ))
                    inserted_labels += 1
                elif label.labels_json != label_payload:
                    raise ValueError("immutable market label conflicts with existing version")
            metadata_payload = self._jsonable({
                **asdict(artifact.metadata), "scaler": asdict(artifact.scaler),
                "statistics": artifact.statistics,
            })
            self.session.add(DatasetMetadataRecord(
                dataset_id=artifact.metadata.dataset_id, created_at=artifact.metadata.created_at,
                symbol=artifact.metadata.symbol, timeframes_json=list(artifact.metadata.timeframes),
                feature_version=artifact.metadata.feature_version, label_version=artifact.metadata.label_version,
                data_start=artifact.metadata.data_start, data_end=artifact.metadata.data_end,
                row_count=artifact.metadata.row_count, schema_hash=artifact.metadata.schema_hash,
                dataset_hash=artifact.metadata.dataset_hash, metadata_json=metadata_payload,
            ))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        return {"features": inserted_features, "labels": inserted_labels, "metadata": 1}

    @classmethod
    def _jsonable(cls, value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): cls._jsonable(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._jsonable(item) for item in value]
        return value
