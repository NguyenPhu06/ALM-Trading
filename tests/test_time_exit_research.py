"""Exit rule research (section 12)."""
import pytest

from research.exits import EXIT_KINDS, ExitResearch, ExitVerdict, capture_ratio
from tests.phase15_helpers import observation, series


def research(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return ExitResearch(**kwargs)


def arms(count=60, best="HYBRID_EXIT"):
    return {kind: series(count, mean=0.0012 if kind == best else 0.0002,
                         seed=index + 1, start=index * 1000, exit_kind=kind)
            for index, kind in enumerate(EXIT_KINDS)}


def test_every_documented_exit_is_named():
    assert EXIT_KINDS == ("FIXED_STOP", "FIXED_TARGET", "TIME_EXIT", "EVEN_HOUR_EXIT",
                          "STRUCTURE_EXIT", "LIQUIDITY_EXIT", "HYBRID_EXIT")


def test_every_exit_family_is_evaluated():
    report = research().run(arms=arms())
    assert set(report.arms) == set(EXIT_KINDS)


def test_observations_are_grouped_by_recorded_exit_kind():
    rows = (series(30, seed=1, exit_kind="TIME_EXIT")
            + series(30, seed=2, start=100, exit_kind="STRUCTURE_EXIT"))
    grouped = research().by_kind(rows)
    assert len(grouped["TIME_EXIT"]) == 30
    assert len(grouped["STRUCTURE_EXIT"]) == 30
    assert grouped["FIXED_STOP"] == []


def test_the_best_exit_comes_from_the_observations():
    assert research().run(arms=arms(best="STRUCTURE_EXIT")).best == "STRUCTURE_EXIT"


def test_the_best_arm_is_marked_best():
    report = research().run(arms=arms(best="HYBRID_EXIT"))
    assert report.arms["HYBRID_EXIT"].verdict is ExitVerdict.BEST


def test_a_significantly_worse_arm_is_marked_worse():
    report = research(minimum_samples=100).run(
        arms={"TIME_EXIT": series(150, mean=0.0009, seed=1, exit_kind="TIME_EXIT"),
              "FIXED_STOP": series(150, mean=0.0001, seed=2, start=1000,
                                   exit_kind="FIXED_STOP")})
    assert report.arms["FIXED_STOP"].verdict is ExitVerdict.WORSE


def test_an_indistinguishable_arm_is_competitive_not_worse():
    report = research(minimum_samples=100).run(
        arms={"TIME_EXIT": series(150, mean=0.0004, seed=1, exit_kind="TIME_EXIT"),
              "EVEN_HOUR_EXIT": series(150, mean=0.00041, seed=2, start=1000,
                                       exit_kind="EVEN_HOUR_EXIT")})
    assert report.arms["EVEN_HOUR_EXIT"].verdict is ExitVerdict.COMPETITIVE


def test_a_thin_arm_is_insufficient_data():
    layout = arms()
    layout["FIXED_STOP"] = series(3, seed=99, start=9000, exit_kind="FIXED_STOP")
    report = research().run(arms=layout)
    assert report.arms["FIXED_STOP"].verdict is ExitVerdict.INSUFFICIENT_DATA
    assert "FIXED_STOP" in report.unreliable


# ------------------------------------------------------------ capture ratio
def test_capture_ratio_measures_realised_over_available():
    rows = [observation(index, net=0.0005, mfe=0.0010) for index in range(10)]
    assert capture_ratio(rows) == pytest.approx(0.5)


def test_capture_ratio_is_none_without_excursion_data():
    rows = [observation(index, net=0.0005, mfe=0) for index in range(10)]
    assert capture_ratio(rows) is None


def test_capture_ratio_is_none_on_an_empty_set():
    assert capture_ratio([]) is None


def test_an_exit_that_leaves_value_behind_has_a_low_capture_ratio():
    greedy = [observation(index, net=0.0009, mfe=0.0010) for index in range(40)]
    timid = [observation(1000 + index, net=0.0001, mfe=0.0010) for index in range(40)]
    report = research().run(arms={"TIME_EXIT": timid, "STRUCTURE_EXIT": greedy})
    assert report.arms["STRUCTURE_EXIT"].capture_ratio > \
        report.arms["TIME_EXIT"].capture_ratio
    assert report.best_capture == "STRUCTURE_EXIT"


def test_a_high_win_rate_does_not_hide_a_low_capture_ratio():
    """Section 12's point: winning often is not the same as winning enough."""
    timid = [observation(index, net=0.00005, mfe=0.0020) for index in range(40)]
    report = research().run(arms={"TIME_EXIT": timid})
    arm = report.arms["TIME_EXIT"]
    assert arm.metrics.win_rate == pytest.approx(1.0)
    assert arm.capture_ratio < 0.05


def test_average_holding_time_is_reported():
    report = research().run(arms=arms())
    assert report.arms["TIME_EXIT"].average_holding == pytest.approx(3600.0)


def test_the_report_explains_the_capture_ratio():
    assert "left value behind" in research().run(arms=arms()).as_dict()["note"]


def test_the_reference_arm_has_no_self_comparison():
    report = research().run(arms=arms(), reference="TIME_EXIT")
    assert report.arms["TIME_EXIT"].significance == {}
    assert report.arms["TIME_EXIT"].deltas == {}
