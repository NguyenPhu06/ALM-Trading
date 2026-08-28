"""Timeframe performance matrix (section 10)."""
import pytest

from research.matrices import MatrixBuilder, signal_quality
from research.models import TIMEFRAMES
from tests.phase15_helpers import observation, series


def builder(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return MatrixBuilder(**kwargs)


def mixed(count=50):
    return (series(count, mean=0.0009, seed=1, timeframe="M5")
            + series(count, mean=-0.0007, seed=2, start=1000, timeframe="H1",
                     correct_rate=0.3))


def test_every_documented_timeframe_is_a_row():
    matrix = builder().timeframe(mixed())
    assert set(matrix.cells) == set(TIMEFRAMES)
    assert TIMEFRAMES == ("D1", "H4", "H1", "M30", "M15", "M5")


def test_m5_performance_says_nothing_about_h1():
    matrix = builder().timeframe(mixed())
    assert "M5" in matrix.profitable
    assert "H1" in matrix.losing


def test_an_untested_timeframe_is_not_a_pass():
    matrix = builder().timeframe(mixed())
    assert matrix.cells["D1"].metrics.sample_size == 0
    assert "D1" not in matrix.profitable
    assert not matrix.cells["D1"].reliable


def test_each_timeframe_is_judged_on_its_own_samples():
    matrix = builder().timeframe(mixed())
    assert matrix.cells["M5"].metrics.sample_size == 50
    assert matrix.cells["H1"].metrics.sample_size == 50
    assert matrix.cells["M15"].metrics.sample_size == 0


def test_expectancy_mae_mfe_and_drawdown_are_reported_per_timeframe():
    row = builder().timeframe(mixed()).cells["M5"].row()
    for column in ("expectancy", "average_mae", "average_mfe", "maximum_drawdown"):
        assert row[column] is not None, column


def test_prediction_accuracy_is_reported_per_timeframe():
    matrix = builder().timeframe(mixed())
    assert matrix.cells["M5"].metrics.prediction_accuracy is not None
    assert (matrix.cells["M5"].metrics.prediction_accuracy
            > matrix.cells["H1"].metrics.prediction_accuracy)


# ---------------------------------------------------------- signal quality
def test_signal_quality_reports_the_directional_rate():
    rows = ([observation(index, predicted="UP") for index in range(30)]
            + [observation(100 + index, predicted="WAIT", correct=None)
               for index in range(10)])
    quality = signal_quality(rows, minimum_samples=30)
    assert quality["samples"] == 40
    assert quality["directional"] == 30
    assert quality["directional_rate"] == pytest.approx(0.75)


def test_signal_quality_reports_accuracy_only_over_judged_rows():
    rows = ([observation(index, correct=True) for index in range(30)]
            + [observation(100 + index, correct=False) for index in range(10)])
    quality = signal_quality(rows)
    assert quality["prediction_accuracy"] == pytest.approx(0.75)


def test_signal_quality_on_an_empty_set_is_not_an_error():
    quality = signal_quality([])
    assert quality["samples"] == 0
    assert quality["prediction_accuracy"] is None


def test_signal_quality_flags_a_small_sample():
    assert signal_quality(series(5, seed=3), minimum_samples=30)["reliable"] is False


def test_an_unrecognised_timeframe_does_not_pollute_a_known_one():
    rows = mixed() + series(35, seed=4, start=2000, timeframe="M3")
    matrix = builder().timeframe(rows)
    assert matrix.cells["M5"].metrics.sample_size == 50
    assert matrix.cells["UNKNOWN"].metrics.sample_size == 35
