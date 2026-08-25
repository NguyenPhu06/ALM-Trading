"""Future model definitions. Intentionally empty in Phase 3."""
from ai.models.contracts import ModelInput, ModelPrediction, StructuredDecisionContext
from ai.models.baselines import DecisionStumpBaseline, MajorityClassBaseline, SoftmaxLogisticBaseline
from ai.models.neural import EpochMetrics, NumpyMLPClassifier, TrainingHistory

__all__ = [
    "ModelInput", "ModelPrediction", "StructuredDecisionContext", "MajorityClassBaseline",
    "SoftmaxLogisticBaseline", "DecisionStumpBaseline", "NumpyMLPClassifier",
    "EpochMetrics", "TrainingHistory",
]
