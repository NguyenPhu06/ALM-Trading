"""Session performance matrix (section 9).

"Do not assume a session is profitable. Use actual observations."
"""
import pytest

from research.matrices import ACTIVE_SESSIONS, MatrixBuilder
from research.models import SESSIONS
from tests.phase15_helpers import series


def builder(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return MatrixBuilder(**kwargs)


def mixed(count=50):
    return (series(count, mean=0.0009, seed=1, session="LONDON")
            + series(count, mean=-0.0008, seed=2, start=1000, session="ASIA",
                     correct_rate=0.3)
            + series(count, mean=0.0002, seed=3, start=2000, session="NEW_YORK")
            + series(count, mean=0.0004, seed=4, start=3000,
                     session="LONDON_NEW_YORK_OVERLAP"))


def test_the_four_active_sessions_are_named():
    assert ACTIVE_SESSIONS == ("ASIA", "LONDON", "NEW_YORK",
                               "LONDON_NEW_YORK_OVERLAP")


def test_every_session_bucket_is_reported():
    matrix = builder().session(mixed())
    assert set(matrix.cells) == set(SESSIONS)


def test_the_overlap_session_is_measured_separately():
    matrix = builder().session(mixed())
    assert matrix.cells["LONDON_NEW_YORK_OVERLAP"].metrics.sample_size == 50
    assert matrix.cells["LONDON"].metrics.sample_size == 50


def test_no_session_is_assumed_profitable():
    """LONDON is the busiest session, and it is still judged on its numbers."""
    rows = series(60, mean=-0.0009, seed=5, session="LONDON", correct_rate=0.3)
    matrix = builder().session(rows)
    assert "LONDON" in matrix.losing
    assert "LONDON" not in matrix.profitable


def test_a_profitable_and_a_losing_session_are_separated():
    matrix = builder().session(mixed())
    assert "LONDON" in matrix.profitable
    assert "ASIA" in matrix.losing


def test_the_best_session_comes_from_the_observations():
    assert builder().session(mixed()).best == "LONDON"
    assert builder().session(mixed()).worst == "ASIA"


def test_an_unnamed_session_lands_in_custom():
    rows = mixed() + series(35, seed=6, start=4000, session="SYDNEY")
    assert builder().session(rows).cells["CUSTOM"].metrics.sample_size == 35


def test_off_session_observations_are_not_discarded():
    rows = mixed() + series(35, seed=7, start=5000, session="OFF_SESSION")
    assert builder().session(rows).cells["OFF_SESSION"].metrics.sample_size == 35


def test_a_thin_session_is_not_judged():
    rows = mixed() + series(3, mean=0.9, seed=8, start=6000, session="OFF_SESSION")
    matrix = builder().session(rows)
    assert not matrix.cells["OFF_SESSION"].reliable
    assert "OFF_SESSION" not in matrix.profitable
    assert matrix.best != "OFF_SESSION"


def test_each_session_reports_mae_mfe_and_drawdown():
    row = builder().session(mixed()).cells["LONDON"].row()
    assert row["average_mae"] is not None
    assert row["average_mfe"] is not None
    assert row["maximum_drawdown"] is not None


def test_the_rows_are_ordered_and_complete():
    matrix = builder().session(mixed())
    rows = matrix.rows()
    assert len(rows) == len(SESSIONS)
    assert [row["name"] for row in rows] == sorted(SESSIONS)


def test_all_three_matrices_are_produced_together():
    payload = builder().all(mixed())
    assert set(payload) == {"regime", "session", "timeframe"}
    assert payload["session"]["dimension"] == "session"
    assert payload["session"]["best"] == "LONDON"
