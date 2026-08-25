import numpy as np

from ai.datasets.model_dataset import ModelDatasetPartition, PreparedModelDataset
from ai.training.trainer import ResearchTrainer
from tests.phase5_helpers import classification_data, model_inputs, training_config


def test_trainer_compares_baselines_and_neural_network_without_tuning_on_test():
    timestamps, matrix, labels, outcomes = classification_data(90)
    inputs = model_inputs(timestamps, matrix)
    partition = lambda name, start, end: ModelDatasetPartition(
        name, inputs[start:end], matrix[start:end], labels[start:end], outcomes[start:end],
    )
    names = inputs[0].feature_names
    dataset = PreparedModelDataset(
        "fixture.v1", "phase4.features.v1", names,
        partition("TRAIN", 0, 60), partition("VALIDATION", 60, 75), partition("TEST", 75, 90),
        {"scaler": {"feature_names": list(names), "means": {name: 0.0 for name in names},
                    "standard_deviations": {name: 1.0 for name in names}, "fitted_split": "TRAIN"}},
    )
    report = ResearchTrainer(training_config(), calibration_bins=5).train(dataset)
    assert set(report.evaluations) == {"majority", "logistic", "tree_stump", "neural_network"}
    for evaluation in report.evaluations.values():
        metrics = evaluation.classification
        assert 0 <= metrics.accuracy <= 1
        assert 0 <= metrics.balanced_accuracy <= 1
        assert set(metrics.per_class) == {"UP", "DOWN", "NEUTRAL"}
        assert len(metrics.confusion_matrix) == 3
        assert evaluation.trading_relevance.disclaimer == "RESEARCH_ASSOCIATION_NOT_STRATEGY_PROFITABILITY"
    assert isinstance(report.neural_network_beats_baseline, bool)
    assert report.history.overfitting_status in {"POSSIBLE_OVERFITTING", "NO_CLEAR_OVERFITTING"}
