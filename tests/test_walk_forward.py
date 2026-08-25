from ai.datasets import ExpandingWalkForward
from ai.evaluation import WalkForwardValidator
from tests.phase5_helpers import classification_data, training_config


def test_walk_forward_trains_expanding_windows_and_keeps_test_after_validation():
    timestamps, matrix, labels, outcomes = classification_data(60)
    validator = WalkForwardValidator(
        ExpandingWalkForward(initial_train_size=24, validation_size=9, test_size=6, step_size=6),
        training_config(),
    )
    results = validator.validate(timestamps, matrix, labels, outcomes)
    assert len(results) >= 2
    assert results[1].window.train_end > results[0].window.train_end
    assert all(result.window.train_end < result.window.validation_start < result.window.test_start for result in results)
    assert all(0 <= result.metrics.balanced_accuracy <= 1 for result in results)
