"""Regime performance matrix (section 8) and regime transitions (section 18)."""
import pytest

from research.matrices import MATRIX_COLUMNS, MatrixBuilder
from research.models import REGIMES
from tests.phase15_helpers import series


def builder(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return MatrixBuilder(**kwargs)


def mixed(*, bull_mean=0.0009, bear_mean=-0.0007, count=60):
    return (series(count, mean=bull_mean, seed=1, regime="BULL")
            + series(count, mean=bear_mean, seed=2, start=1000, regime="BEAR",
                     correct_rate=0.3))


# ------------------------------------------------------------- the five regimes
def test_every_documented_regime_is_a_row():
    matrix = builder().regime(mixed())
    assert set(matrix.cells) == set(REGIMES)
    for name in ("STRONG_BULL", "BULL", "RANGE", "BEAR", "STRONG_BEAR"):
        assert name in matrix.cells


def test_an_empty_regime_is_still_reported():
    matrix = builder().regime(mixed())
    assert matrix.cells["STRONG_BULL"].metrics.sample_size == 0
    assert not matrix.cells["STRONG_BULL"].reliable


def test_every_documented_column_is_present():
    row = builder().regime(mixed()).rows()[0]
    for column in ("sample_size", "win_rate", "expectancy", "net_pnl",
                   "maximum_drawdown", "average_mae", "average_mfe"):
        assert column in row, column
    assert MATRIX_COLUMNS == ("sample_size", "win_rate", "expectancy", "net_pnl",
                              "maximum_drawdown", "average_mae", "average_mfe")


def test_the_best_and_worst_regimes_are_identified():
    matrix = builder().regime(mixed())
    assert matrix.best == "BULL"
    assert matrix.worst == "BEAR"


def test_profitable_and_losing_regimes_are_separated():
    matrix = builder().regime(mixed())
    assert matrix.profitable == ("BULL",)
    assert matrix.losing == ("BEAR",)


def test_a_thin_regime_is_reported_but_not_reliable():
    rows = mixed() + series(4, mean=0.05, seed=3, start=5000, regime="RANGE")
    matrix = builder().regime(rows)
    cell = matrix.cells["RANGE"]
    assert cell.metrics.sample_size == 4
    assert not cell.reliable
    assert cell.metrics.expectancy is not None, "the numbers stay visible"


def test_an_unreliable_regime_is_never_the_best():
    rows = mixed() + series(4, mean=0.5, seed=3, start=5000, regime="RANGE")
    assert builder().regime(rows).best == "BULL"


def test_an_unknown_regime_falls_into_unknown():
    rows = mixed() + series(35, seed=4, start=6000, regime="CHOPPY")
    assert builder().regime(rows).cells["UNKNOWN"].metrics.sample_size == 35


def test_each_cell_carries_the_full_metric_set():
    payload = builder().regime(mixed()).cells["BULL"].as_dict()["metrics"]
    for name in ("profit_factor", "sharpe_like", "sortino_like", "calibration",
                 "return_over_drawdown", "tail_loss"):
        assert name in payload, name


def test_the_aggregate_does_not_hide_a_losing_regime():
    rows = (series(120, mean=0.0012, seed=5, regime="BULL")
            + series(60, mean=-0.0008, seed=6, start=1000, regime="BEAR"))
    total = sum(row.net_pnl for row in rows)
    matrix = builder().regime(rows)
    assert total > 0, "profitable overall"
    assert "BEAR" in matrix.losing, "and still losing in BEAR"


# ------------------------------------------------------- 18. regime transitions
def test_a_transition_is_only_counted_when_the_regime_changed():
    steady = series(30, seed=7, regime="BULL", previous_regime="BULL")
    assert builder().transitions(steady).cells == {}


def test_a_transition_is_named_from_and_to():
    rows = series(40, seed=8, regime="RANGE", previous_regime="BULL")
    matrix = builder().transitions(rows)
    assert "BULL->RANGE" in matrix.cells


def test_several_transitions_are_tracked_separately():
    rows = (series(35, seed=9, regime="RANGE", previous_regime="BULL")
            + series(35, seed=10, start=1000, regime="BULL", previous_regime="RANGE")
            + series(35, seed=11, start=2000, regime="BEAR", previous_regime="BULL"))
    matrix = builder().transitions(rows)
    assert set(matrix.cells) == {"BULL->RANGE", "RANGE->BULL", "BULL->BEAR"}


def test_the_transition_study_contrasts_moving_and_steady_states():
    rows = (series(60, mean=-0.0009, seed=12, regime="BEAR", previous_regime="BULL")
            + series(60, mean=0.0009, seed=13, start=1000, regime="BULL"))
    study = builder().transition_study(rows)
    assert study["during_transition"]["expectancy"] < 0
    assert study["steady_state"]["expectancy"] > 0
    assert study["observed_transitions"] == ["BULL->BEAR"]


def test_the_transition_study_names_the_worst_transition():
    rows = (series(40, mean=-0.0012, seed=14, regime="BEAR", previous_regime="BULL")
            + series(40, mean=0.0008, seed=15, start=1000, regime="BULL",
                     previous_regime="RANGE"))
    study = builder().transition_study(rows)
    assert study["worst_transition"] == "BULL->BEAR"
    assert study["best_transition"] == "RANGE->BULL"


def test_the_transition_study_disclaims_causation():
    study = builder().transition_study(series(40, seed=16, regime="BEAR",
                                              previous_regime="BULL"))
    assert "not a claim about causation" in study["note"]


def test_an_observation_without_a_previous_regime_has_no_transition():
    rows = series(10, seed=17)
    assert all(row.regime_transition is None for row in rows)
