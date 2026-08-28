"""Does the NN earn its place? (section 13)

The default answer is NN_VALUE_NOT_PROVEN, and the NN is never forced into the
strategy.
"""
import pytest

from research.nn_value import DELTA_FIELDS, NNValueTest, NNValueVerdict
from tests.phase15_helpers import observation, series


def build(**kwargs):
    """Not named test*: pytest collects every module-level name with that prefix."""
    kwargs.setdefault("minimum_samples", 100)
    return NNValueTest(**kwargs)


def run(*, without=0.0004, with_nn=0.0004, count=150, **kwargs):
    return build(**kwargs).run(
        without_nn=series(count, mean=without, seed=1, confidence=None),
        with_nn=series(count, mean=with_nn, seed=2, start=1000))


def test_every_documented_delta_is_reported():
    payload = run().as_dict()
    assert set(payload["deltas"]) == set(DELTA_FIELDS)
    assert set(DELTA_FIELDS) == {"expectancy", "win_rate", "maximum_drawdown",
                                 "average_mae", "average_mfe", "calibration"}


def test_an_indistinguishable_nn_is_not_proven():
    """The default verdict when the evidence does not clear the bar."""
    report = run(without=0.0004, with_nn=0.00041)
    assert report.verdict is NNValueVerdict.NN_VALUE_NOT_PROVEN
    assert report.proven is False


def test_a_clearly_better_nn_adds_value():
    report = run(without=0.0002, with_nn=0.0012)
    assert report.verdict is NNValueVerdict.NN_ADDS_VALUE
    assert report.proven is True
    assert report.deltas["expectancy"] > 0


def test_a_clearly_worse_nn_is_harmful():
    report = run(without=0.0012, with_nn=0.0001)
    assert report.verdict is NNValueVerdict.NN_HARMFUL
    assert report.deltas["expectancy"] < 0


def test_a_slightly_worse_nn_is_not_proven_rather_than_harmful():
    report = run(without=0.00041, with_nn=0.0004)
    assert report.verdict is NNValueVerdict.NN_VALUE_NOT_PROVEN
    assert "EXPECTANCY_LOWER_WITH_NN" in report.reasons


def test_too_few_samples_is_insufficient_data():
    report = run(count=20)
    assert report.verdict is NNValueVerdict.INSUFFICIENT_DATA
    assert any("SAMPLE_BELOW_MINIMUM" in reason for reason in report.reasons)


def test_a_better_mean_with_a_worse_drawdown_is_not_proven():
    """A higher average bought with a deeper hole is not an improvement."""
    report = build().run(
        without_nn=series(400, mean=0.0002, deviation=0.0002, seed=1, confidence=None),
        with_nn=series(400, mean=0.0030, deviation=0.0060, seed=2, start=1000))
    assert report.significance["significant"], "the mean really did improve"
    assert report.deltas["expectancy"] > 0
    assert report.deltas["maximum_drawdown"] > 0
    assert report.verdict is NNValueVerdict.NN_VALUE_NOT_PROVEN
    assert "DRAWDOWN_WORSE_WITH_NN" in report.reasons


def test_the_report_states_that_the_nn_is_not_forced():
    assert "not forced into the strategy" in run().as_dict()["note"]


def test_not_proven_is_documented_as_a_state_of_the_evidence():
    assert "state of the evidence" in run().as_dict()["note"]


def test_both_arms_are_reported_in_full():
    payload = run().as_dict()
    assert payload["without_nn"]["sample_size"] == 150
    assert payload["with_nn"]["sample_size"] == 150


def test_the_significance_detail_is_carried_through():
    payload = run(without=0.0002, with_nn=0.0012).as_dict()
    assert payload["significance"]["significant"] is True
    assert payload["significance"]["effect_band"] in {"SMALL", "MEDIUM", "LARGE"}


# ------------------------------------------------------- splitting one set
def test_split_separates_observations_that_carried_a_prediction():
    rows = (series(150, mean=0.0002, seed=1, confidence=None)
            + series(150, mean=0.0012, seed=2, start=1000, confidence=0.7))
    report = build().split(rows)
    assert report.without_nn.sample_size == 150
    assert report.with_nn.sample_size == 150
    assert report.verdict is NNValueVerdict.NN_ADDS_VALUE


def test_split_with_no_predictions_is_insufficient_data():
    report = build().split(series(150, seed=1, confidence=None))
    assert report.verdict is NNValueVerdict.INSUFFICIENT_DATA


def test_calibration_delta_is_reported_when_both_arms_have_confidence():
    report = build().run(
        without_nn=series(150, mean=0.0004, seed=1, confidence=0.5),
        with_nn=series(150, mean=0.0004, seed=2, start=1000, confidence=0.9))
    assert report.deltas["calibration"] is not None
