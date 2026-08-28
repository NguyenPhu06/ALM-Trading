"""Dataset ingestion for labelled observations (section 9).

An observation only reaches the learning dataset after its horizon elapsed and a
label was produced. This module is the gate between the two: it checks the three
versions agree, refuses a row it has already seen, and records the result.

It writes training data. It does not train — see `ai/training/pipeline.py` for
the explicit job, and section 10 for why the two are separate.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from ai.dataset.versioning import FEATURE_VERSION, LABEL_VERSION, PREPROCESSING_VERSION
from ai.edge.evidence import EvidenceSource
from observation.lifecycle import ObservationStatus

logger = logging.getLogger(__name__)


class IngestionRefusal(StrEnum):
    NOT_LABELED = "NOT_LABELED"
    MISSING_LABEL = "MISSING_LABEL"
    DUPLICATE_ROW = "DUPLICATE_ROW"
    FEATURE_VERSION_MISMATCH = "FEATURE_VERSION_MISMATCH"
    LABEL_VERSION_MISMATCH = "LABEL_VERSION_MISMATCH"
    NO_ENTRY_PRICE = "NO_ENTRY_PRICE"


@dataclass(frozen=True, slots=True)
class IngestionResult:
    accepted: bool
    observation_id: str
    refusal: IngestionRefusal | None = None
    dataset_version: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "observation_id": self.observation_id,
                "refusal": str(self.refusal) if self.refusal else None,
                "dataset_version": self.dataset_version,
                "evidence": str(EvidenceSource.FORWARD_OBSERVATION), **self.context}


class DatasetIngestor:
    """Accepts labelled observations into the learning store, exactly once."""

    def __init__(self, repository: Any = None, *, feature_version: str = FEATURE_VERSION,
                 label_version: str = LABEL_VERSION,
                 preprocessing_version: str = PREPROCESSING_VERSION):
        self.repository = repository
        self.feature_version = feature_version
        self.label_version = label_version
        self.preprocessing_version = preprocessing_version
        self._seen: set[str] = set()

    @property
    def dataset_version(self) -> str:
        return f"{self.feature_version}.{self.label_version}.{self.preprocessing_version}"

    def seen(self, observation_id: str) -> bool:
        if observation_id in self._seen:
            return True
        if self.repository is None:
            return False
        try:
            return bool(self.repository.dataset_row_exists(observation_id))
        except Exception:
            logger.exception("duplicate check failed for %s", observation_id)
            return False

    def ingest(self, observation: Any, outcome: Any) -> IngestionResult:
        """Validate and record one row. Refusals are reported, never raised."""
        observation_id = str(getattr(observation, "observation_id", ""))

        if getattr(observation, "status", None) not in {
                ObservationStatus.LABELED, ObservationStatus.OUTCOME_CALCULATED}:
            return IngestionResult(False, observation_id, IngestionRefusal.NOT_LABELED)

        label = getattr(outcome, "label", None)
        if label is None:
            return IngestionResult(False, observation_id, IngestionRefusal.MISSING_LABEL)

        if observation.feature_version and observation.feature_version != self.feature_version:
            # A row built from a different feature set would silently corrupt the
            # dataset: the columns would not mean the same thing.
            return IngestionResult(False, observation_id,
                                   IngestionRefusal.FEATURE_VERSION_MISMATCH,
                                   context={"expected": self.feature_version,
                                            "found": observation.feature_version})

        found_label_version = getattr(label, "label_version", None)
        if found_label_version and found_label_version != self.label_version:
            return IngestionResult(False, observation_id,
                                   IngestionRefusal.LABEL_VERSION_MISMATCH,
                                   context={"expected": self.label_version,
                                            "found": found_label_version})

        if observation.entry_price is None:
            return IngestionResult(False, observation_id, IngestionRefusal.NO_ENTRY_PRICE)

        if self.seen(observation_id):
            return IngestionResult(False, observation_id, IngestionRefusal.DUPLICATE_ROW)

        self._seen.add(observation_id)
        if self.repository is not None:
            try:
                self.repository.attach_label(
                    observation_id, label, future_price=outcome.future_price)
            except Exception:
                logger.exception("failed to attach label for %s", observation_id)
                self._seen.discard(observation_id)
                raise
        return IngestionResult(True, observation_id, None, self.dataset_version,
                               context={"horizon": outcome.horizon,
                                        "net_pnl": outcome.net_hypothetical_pnl,
                                        "resolved_at": _stamp(outcome.resolved_at)})


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
