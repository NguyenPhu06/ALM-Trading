"""Versions and dataset identity.

Feature definitions are never changed silently. If a feature is added, removed or
redefined, the FEATURE_VERSION constant moves and old datasets keep their own
version, so a row always states the definition it was built under.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

FEATURE_VERSION = "features_v1"
LABEL_VERSION = "labels_v1"
PREPROCESSING_VERSION = "scaler_v1"
DATASET_SCHEMA_VERSION = "dataset_v1"


@dataclass(frozen=True, slots=True)
class DatasetAudit:
    """The record every training dataset must carry (section 35)."""

    dataset_id: str
    feature_version: str
    label_version: str
    preprocessing_version: str
    start: datetime | None
    end: datetime | None
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    row_count: int
    class_distribution: dict[str, int]
    missing_values: int
    duplicate_count: int
    source: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    horizon: str | None = None
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id, "feature_version": self.feature_version,
            "label_version": self.label_version,
            "preprocessing_version": self.preprocessing_version,
            "start": self.start, "end": self.end, "symbols": list(self.symbols),
            "timeframes": list(self.timeframes), "row_count": self.row_count,
            "class_distribution": dict(self.class_distribution),
            "missing_values": self.missing_values, "duplicate_count": self.duplicate_count,
            "source": self.source, "created_at": self.created_at, "horizon": self.horizon,
            "notes": list(self.notes),
        }


def content_hash(payload: Any) -> str:
    """Stable hash of a payload, so an identical dataset gets an identical id."""
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def dataset_id(*, feature_version: str, label_version: str, symbols: Sequence[str],
               timeframes: Sequence[str], horizon: str, rows: int,
               start: datetime | None, end: datetime | None) -> str:
    digest = content_hash({
        "feature_version": feature_version, "label_version": label_version,
        "symbols": sorted(symbols), "timeframes": sorted(timeframes),
        "horizon": horizon, "rows": rows,
        "start": start.isoformat() if start else None,
        "end": end.isoformat() if end else None,
    })
    return f"{feature_version}.{label_version}.{digest[:16]}"
