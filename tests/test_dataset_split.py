from ai.datasets import ChronologicalSplitter
from tests.phase5_helpers import classification_data


def test_phase5_dataset_split_is_strictly_chronological():
    timestamps, *_ = classification_data(30)
    split = ChronologicalSplitter(train_ratio=0.7, validation_ratio=0.15).split(timestamps)
    assert split.train.end_time < split.validation.start_time
    assert split.validation.end_time < split.test.start_time
    assert [split.name_for_index(index) for index in range(30)] == sorted(
        [split.name_for_index(index) for index in range(30)],
        key={"TRAIN": 0, "VALIDATION": 1, "TEST": 2}.get,
    )
