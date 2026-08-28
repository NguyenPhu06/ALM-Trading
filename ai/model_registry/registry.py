"""The model registry: lifecycle, champion selection, artifact separation.

Artifacts live on disk under `phase_13.artifacts_path` (gitignored); the registry
holds metadata only. Nothing here writes a credential into an artifact, and the
registry refuses to store one.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ai.model_registry.comparison import ChampionChallengerComparator, ComparisonResult
from ai.model_registry.records import (
    ALLOWED_TRANSITIONS,
    ApprovalToken,
    InvalidModelTransition,
    ModelRecord,
    ModelState,
    ModelTask,
)
from config.settings import ROOT, get_settings, load_yaml

logger = logging.getLogger(__name__)

CREDENTIAL_KEYS = ("password", "secret", "token", "credential", "api_key", "login")


class PromotionRefused(RuntimeError):
    """Raised when promotion is attempted without approval or without evidence."""


def scrub_artifact(payload: Any) -> Any:
    """A model artifact must never carry a credential (section 28)."""
    if isinstance(payload, dict):
        return {str(key): scrub_artifact(value) for key, value in payload.items()
                if not any(token in str(key).lower() for token in CREDENTIAL_KEYS)}
    if isinstance(payload, (list, tuple)):
        return [scrub_artifact(item) for item in payload]
    return payload


class ModelRegistry:
    """In-memory registry with optional on-disk artifacts and DB persistence."""

    def __init__(self, *, artifacts_path: str | Path | None = None,
                 comparator: ChampionChallengerComparator | None = None,
                 repository: Any = None):
        config = load_yaml().get("phase_13", {})
        self.artifacts_path = Path(artifacts_path or config.get("artifacts_path")
                                   or ROOT / "data" / "models")
        self.comparator = comparator or ChampionChallengerComparator()
        self.repository = repository
        self._records: dict[str, ModelRecord] = {}

    # ------------------------------------------------------------------ basics
    def register(self, record: ModelRecord) -> ModelRecord:
        if record.model_id in self._records:
            raise ValueError(f"model {record.model_id} is already registered")
        self._records[record.model_id] = record
        self._persist(record)
        return record

    def get(self, model_id: str) -> ModelRecord | None:
        return self._records.get(model_id)

    def all(self) -> tuple[ModelRecord, ...]:
        return tuple(self._records.values())

    def for_task(self, task: ModelTask) -> tuple[ModelRecord, ...]:
        return tuple(record for record in self._records.values()
                     if record.task.key == task.key)

    def champion(self, task: ModelTask) -> ModelRecord | None:
        return next((record for record in self.for_task(task) if record.is_champion), None)

    def challengers(self, task: ModelTask) -> tuple[ModelRecord, ...]:
        return tuple(record for record in self.for_task(task)
                     if record.state in {ModelState.VALIDATED, ModelState.CANDIDATE})

    # -------------------------------------------------------------- lifecycle
    def transition(self, model_id: str, target: ModelState, *,
                   note: str | None = None) -> ModelRecord:
        record = self._require(model_id)
        if target not in ALLOWED_TRANSITIONS[record.state]:
            raise InvalidModelTransition(
                f"invalid model transition: {record.state} -> {target}")
        updated = replace(record, state=target,
                          notes=(*record.notes, note) if note else record.notes)
        self._records[model_id] = updated
        self._persist(updated)
        return updated

    def reject(self, model_id: str, reason: str) -> ModelRecord:
        return self.transition(model_id, ModelState.REJECTED, note=f"REJECTED:{reason}")

    def retire(self, model_id: str, reason: str) -> ModelRecord:
        return self.transition(model_id, ModelState.RETIRED, note=f"RETIRED:{reason}")

    # ------------------------------------------------------------- promotion
    def evaluate_promotion(self, model_id: str) -> ComparisonResult:
        """Compare a challenger with the incumbent. Recommends only."""
        challenger = self._require(model_id)
        return self.comparator.compare(self.champion(challenger.task), challenger)

    def promote(self, model_id: str, approval: ApprovalToken | None = None, *,
                force: bool = False) -> ModelRecord:
        """Promote to CHAMPION. Requires a human ApprovalToken; never automatic.

        `force` skips only the metric comparison, never the approval requirement,
        and is meant for promoting the first model of a task.
        """
        challenger = self._require(model_id)
        if get_settings().ai_auto_promote:
            # Defence in depth: Settings already refuses to construct with this on.
            raise PromotionRefused("automatic promotion is disabled")
        if approval is None:
            raise PromotionRefused("promotion requires an explicit human approval token")

        comparison = self.evaluate_promotion(model_id)
        if not comparison.recommend_promotion and not force:
            raise PromotionRefused(
                f"challenger did not out-perform the champion: {', '.join(comparison.reasons)}")

        if challenger.state is ModelState.VALIDATED:
            challenger = self.transition(model_id, ModelState.CANDIDATE,
                                         note="promoted to candidate")
        if challenger.state is not ModelState.CANDIDATE:
            raise PromotionRefused(f"only a CANDIDATE may be promoted, not {challenger.state}")

        incumbent = self.champion(challenger.task)
        if incumbent is not None:
            self.retire(incumbent.model_id, f"replaced by {model_id}")

        promoted = replace(self._records[model_id], state=ModelState.CHAMPION,
                           approval=approval,
                           notes=(*self._records[model_id].notes,
                                  f"PROMOTED_BY:{approval.approved_by}"))
        self._records[model_id] = promoted
        self._persist(promoted)
        logger.info("model %s promoted to CHAMPION by %s", model_id, approval.approved_by)
        return promoted

    # ------------------------------------------------------------- artifacts
    def save_artifact(self, model_id: str, payload: dict[str, Any]) -> Path:
        """Write the artifact outside source control, with credentials stripped."""
        record = self._require(model_id)
        directory = self.artifacts_path / record.model_version
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{model_id}.json"
        cleaned = scrub_artifact(payload)
        path.write_text(json.dumps(cleaned, indent=2, sort_keys=True, default=str),
                        encoding="utf-8")
        self._records[model_id] = replace(record, artifact_path=str(path))
        self._persist(self._records[model_id])
        return path

    def load_artifact(self, model_id: str) -> dict[str, Any] | None:
        record = self._require(model_id)
        if not record.artifact_path:
            return None
        path = Path(record.artifact_path)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ misc
    def _require(self, model_id: str) -> ModelRecord:
        record = self._records.get(model_id)
        if record is None:
            raise KeyError(f"unknown model: {model_id}")
        return record

    def _persist(self, record: ModelRecord) -> None:
        if self.repository is None:
            return
        try:
            self.repository.save_model(record)
        except Exception:
            logger.exception("failed to persist model record %s", record.model_id)

    def summary(self, task: ModelTask | None = None) -> dict[str, Any]:
        records = self.for_task(task) if task else self.all()
        champion = self.champion(task) if task else next(
            (record for record in records if record.is_champion), None)
        return {
            "total": len(records),
            "by_state": {state.value: sum(1 for record in records if record.state is state)
                         for state in ModelState},
            "champion": champion.as_dict() if champion else None,
            "challengers": [record.model_id for record in records
                            if record.state in {ModelState.VALIDATED, ModelState.CANDIDATE}],
        }
