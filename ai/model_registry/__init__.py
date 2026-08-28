"""Phase 13 model registry: lifecycle, champion/challenger, drift.

Distinct from `ai.models.registry` (Phase 5), which stores immutable NumPy MLP
artifacts. This package governs which model is authoritative and how one replaces
another — always with a human in the loop.
"""
from ai.model_registry.comparison import (
    CRITERIA, ChampionChallengerComparator, ComparisonResult, CriterionResult,
)
from ai.model_registry.drift import (
    DriftKind, DriftMonitor, DriftReport, DriftSeverity, DriftSignal,
    population_stability_index,
)
from ai.model_registry.records import (
    ALLOWED_TRANSITIONS, ApprovalToken, InvalidModelTransition, ModelRecord, ModelState,
    ModelTask,
)
from ai.model_registry.registry import ModelRegistry, PromotionRefused, scrub_artifact

__all__ = [
    "ALLOWED_TRANSITIONS", "ApprovalToken", "CRITERIA", "ChampionChallengerComparator",
    "ComparisonResult", "CriterionResult", "DriftKind", "DriftMonitor", "DriftReport",
    "DriftSeverity", "DriftSignal", "InvalidModelTransition", "ModelRecord",
    "ModelRegistry", "ModelState", "ModelTask", "PromotionRefused",
    "population_stability_index", "scrub_artifact",
]
