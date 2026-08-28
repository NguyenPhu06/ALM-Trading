"""DCA projection: bounded, fully costed, and never executed."""
import pytest

from observation.dca_analysis import DCAAnalyzer, DCAProjection


def project(**overrides):
    payload = dict(symbol="EURUSD", direction="BUY", entry=1.1000, volume=0.10,
                   balance=10_000.0)
    payload.update(overrides)
    return DCAAnalyzer().project(**payload)


def test_a_projection_plans_the_configured_number_of_levels():
    projection = project()
    assert len(projection.levels) == projection.max_levels == 3


def test_long_dca_levels_sit_below_the_entry():
    projection = project(direction="BUY")
    assert all(level.price < projection.initial_entry for level in projection.levels)


def test_short_dca_levels_sit_above_the_entry():
    projection = project(direction="SELL")
    assert all(level.price > projection.initial_entry for level in projection.levels)


def test_each_level_is_further_from_the_entry_than_the_last():
    distances = [level.distance_from_entry for level in project().levels]
    assert distances == sorted(distances)


def test_the_average_entry_moves_toward_the_added_levels():
    projection = project(direction="BUY")
    assert projection.average_entry < projection.initial_entry


def test_cumulative_volume_and_risk_accumulate():
    projection = project()
    volumes = [level.cumulative_volume for level in projection.levels]
    risks = [level.cumulative_risk for level in projection.levels]
    assert volumes == sorted(volumes) and risks == sorted(risks)
    assert projection.total_volume == volumes[-1]


def test_aggregate_exposure_is_reported():
    assert project().aggregate_exposure > 0


def test_a_maximum_theoretical_loss_is_always_stated():
    """The whole point: the worst case must be visible before anyone averages down."""
    projection = project()
    assert projection.maximum_theoretical_loss > 0
    assert projection.bounded


def test_an_explicit_stop_loss_defines_the_invalidation():
    projection = project(stop_loss=1.0900)
    assert projection.invalidation_price == 1.0900
    assert projection.invalidation_condition == "STOP_LOSS_BREACHED"


def test_without_a_stop_the_ladder_is_still_bounded():
    projection = project(stop_loss=None)
    assert projection.invalidation_condition == "PRICE_BEYOND_FINAL_DCA_LEVEL"
    assert projection.maximum_theoretical_loss > 0
    assert projection.bounded, "an unbounded ladder would hide unlimited risk"


def test_a_deeper_stop_produces_a_larger_maximum_loss():
    near = project(stop_loss=1.0950).maximum_theoretical_loss
    far = project(stop_loss=1.0800).maximum_theoretical_loss
    assert far > near


def test_more_levels_increase_the_worst_case():
    shallow = DCAAnalyzer(max_levels=1).project(symbol="EURUSD", direction="BUY",
                                                entry=1.1, volume=0.1)
    deep = DCAAnalyzer(max_levels=5).project(symbol="EURUSD", direction="BUY",
                                             entry=1.1, volume=0.1)
    assert deep.total_volume > shallow.total_volume
    assert deep.maximum_theoretical_loss > shallow.maximum_theoretical_loss


def test_a_projection_never_executes():
    projection = project()
    assert projection.executed is False
    assert projection.as_dict()["executed"] is False
    assert "ANALYSIS_ONLY_NOT_EXECUTED" in projection.reasons
    for name in ("send", "execute", "submit", "place"):
        assert not hasattr(DCAProjection, name), name


def test_the_analyzer_has_no_execution_method():
    for name in ("send_order", "execute", "place_dca", "submit"):
        assert not hasattr(DCAAnalyzer, name), name


def test_an_invalid_entry_is_reported():
    projection = project(entry=0, volume=0)
    assert "INVALID_ENTRY_OR_VOLUME" in projection.reasons
