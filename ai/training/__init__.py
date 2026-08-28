"""Training workflows. Fitting a model is always an explicit job, never a side effect.

The Phase 14 members are exposed lazily. `ai.models` imports `ai.training.config`
at module scope, so eagerly importing the pipeline here would form a cycle:

    ai.training -> ai.training.pipeline -> ai.edge -> ai.evaluation -> ai.models
        -> ai.models.baselines -> ai.training.config -> ai.training (partial)

Deferring the heavy names keeps the package importable from either direction.
"""
from typing import Any

from ai.training.config import TrainingConfig
from ai.training.imbalance import (
    CLASS_NAMES, CLASS_TO_INDEX, ClassImbalanceReport, analyze_class_imbalance,
)
from ai.training.reproducibility import set_reproducible_seed

# name -> defining submodule
_LAZY = {
    "TrainingJob": "ai.training.train",
    "JobResult": "ai.training.train",
    "OnlineLearningRefused": "ai.training.train",
    "TrainingPipeline": "ai.training.pipeline",
    "PipelineReport": "ai.training.pipeline",
    "PipelineStep": "ai.training.pipeline",
    "StepResult": "ai.training.pipeline",
    "ChallengerEvaluator": "ai.training.evaluation",
    "ChallengerEvaluation": "ai.training.evaluation",
    "EvaluationVerdict": "ai.training.evaluation",
    "TrainingTriggerPolicy": "ai.training.triggers",
    "TriggerSettings": "ai.training.triggers",
    "TriggerDecision": "ai.training.triggers",
}

__all__ = [
    "TrainingConfig", "CLASS_NAMES", "CLASS_TO_INDEX", "ClassImbalanceReport",
    "analyze_class_imbalance", "set_reproducible_seed", *_LAZY,
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
