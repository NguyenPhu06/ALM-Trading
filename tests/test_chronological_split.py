"""Chronological splitting; random splitting is refused outright (section 10)."""
from datetime import timedelta

import pytest

from ai.dataset.split import (
    RandomSplitRefused, build_splitter, random_split, split_bounds,
)
from tests.phase13_helpers import NOW, build_dataset


def timestamps(count=100):
    return [NOW - timedelta(hours=count - index) for index in range(count)]


def test_the_split_is_chronological_and_contiguous():
    split = build_splitter().split(timestamps())
    assert split.train.end_index < split.validation.start_index
    assert split.validation.end_index < split.test.start_index
    assert split.train.start_index == 0


def test_the_default_ratios_are_seventy_fifteen_fifteen():
    split = build_splitter().split(timestamps(100))
    train = split.train.end_index - split.train.start_index + 1
    validation = split.validation.end_index - split.validation.start_index + 1
    test = split.test.end_index - split.test.start_index + 1
    assert train == 70 and validation == 15 and test == 15


def test_the_ratios_are_configurable():
    split = build_splitter(train_ratio=0.5, validation_ratio=0.25).split(timestamps(100))
    train = split.train.end_index - split.train.start_index + 1
    assert train == 50


def test_train_ends_before_validation_which_ends_before_test():
    bounds = split_bounds(build_splitter().split(timestamps()))
    assert bounds["train"][1] < bounds["validation"][0]
    assert bounds["validation"][1] < bounds["test"][0]


def test_random_splitting_is_refused():
    with pytest.raises(RandomSplitRefused, match="never be split randomly"):
        random_split(timestamps())


def test_non_increasing_timestamps_are_refused():
    rows = timestamps(10)
    rows[5] = rows[4]
    with pytest.raises(ValueError, match="strictly increasing"):
        build_splitter().split(rows)


def test_a_built_dataset_partitions_chronologically():
    dataset = build_dataset()
    assert dataset.train.rows and dataset.validation.rows and dataset.test.rows
    assert dataset.train.rows[-1].timestamp < dataset.validation.rows[0].timestamp
    assert dataset.validation.rows[-1].timestamp < dataset.test.rows[0].timestamp


def test_partitions_do_not_overlap():
    dataset = build_dataset()
    train = {row.timestamp for row in dataset.train.rows}
    validation = {row.timestamp for row in dataset.validation.rows}
    test = {row.timestamp for row in dataset.test.rows}
    assert not (train & validation) and not (validation & test) and not (train & test)
