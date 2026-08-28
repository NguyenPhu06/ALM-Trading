"""DCA research (section 11).

The rule under test: a DCA configuration is rejected when it buys a higher win
rate with materially worse tail risk.
"""
import random

import pytest

from research.dca import DCA_ARMS, DCAResearch, DCAVerdict, arm_for
from tests.phase15_helpers import NOW, observation, series


def research(**kwargs):
    kwargs.setdefault("minimum_samples", 30)
    return DCAResearch(**kwargs)


def fat_tailed(count=150, *, seed=7, start=1000, win_share=23, win_mean=0.0004,
               tail_mean=-0.006, dca_levels=3):
    """High win rate, small wins, rare very large losses."""
    generator = random.Random(seed)
    rows = []
    for index in range(count):
        net = (generator.gauss(win_mean, 0.0001) if index % 25 < win_share
               else generator.gauss(tail_mean, 0.001))
        rows.append(observation(start + index, net=net, correct=net > 0,
                                dca_levels=dca_levels,
                                margin_used=100.0 * (1 + dca_levels)))
    return rows


def symmetric(count=150, *, seed=3, start=0, mean=0.0008, loss=-0.0009, win_share=6):
    generator = random.Random(seed)
    rows = []
    for index in range(count):
        net = (generator.gauss(mean, 0.0003) if index % 10 < win_share
               else generator.gauss(loss, 0.0003))
        rows.append(observation(start + index, net=net, correct=net > 0,
                                dca_levels=0, margin_used=100.0))
    return rows


# ------------------------------------------------------------------- the arms
def test_every_documented_arm_is_named():
    assert DCA_ARMS == ("NO_DCA", "DCA_1", "DCA_2", "DCA_3")


@pytest.mark.parametrize("levels,expected", [(0, "NO_DCA"), (1, "DCA_1"), (2, "DCA_2"),
                                             (3, "DCA_3"), (9, "DCA_3")])
def test_levels_map_onto_arms(levels, expected):
    assert arm_for(levels) == expected


def test_observations_are_grouped_by_their_recorded_levels():
    rows = (series(40, seed=1, dca_levels=0) + series(40, seed=2, start=100, dca_levels=1)
            + series(40, seed=3, start=200, dca_levels=3))
    grouped = research().by_levels(rows)
    assert len(grouped["NO_DCA"]) == 40
    assert len(grouped["DCA_1"]) == 40
    assert len(grouped["DCA_3"]) == 40
    assert grouped["DCA_2"] == []


def test_a_no_dca_arm_is_required():
    with pytest.raises(KeyError, match="NO_DCA"):
        research().run(arms={"DCA_1": series(50, seed=1)})


# ------------------------------------------- the rule section 11 asks for
def test_a_higher_win_rate_bought_with_tail_risk_is_rejected():
    report = research().run(arms={"NO_DCA": symmetric(), "DCA_3": fat_tailed()})
    arm = report.arms["DCA_3"]
    assert arm.metrics.win_rate > report.baseline.win_rate, "win rate did go up"
    assert arm.verdict is DCAVerdict.REJECTED_TAIL_RISK
    assert "WIN_RATE_BOUGHT_WITH_TAIL_RISK" in arm.reasons


def test_the_rejection_names_the_tail_and_the_drawdown():
    report = research().run(arms={"NO_DCA": symmetric(), "DCA_3": fat_tailed()})
    reasons = report.arms["DCA_3"].reasons
    assert "TAIL_RISK_WORSE" in reasons
    assert "DRAWDOWN_WORSE" in reasons


def test_a_rejected_arm_is_never_recommended():
    report = research().run(arms={"NO_DCA": symmetric(), "DCA_3": fat_tailed()})
    assert "DCA_3" in report.rejected
    assert report.recommended == "NO_DCA"


def test_tail_loss_is_reported_for_every_arm():
    report = research().run(arms={"NO_DCA": symmetric(), "DCA_3": fat_tailed()})
    assert report.arms["NO_DCA"].tail_loss is not None
    assert report.arms["DCA_3"].tail_loss < report.arms["NO_DCA"].tail_loss


def test_margin_usage_is_reported_per_arm():
    report = research().run(arms={"NO_DCA": symmetric(), "DCA_3": fat_tailed()})
    assert report.arms["NO_DCA"].average_margin == pytest.approx(100.0)
    assert report.arms["DCA_3"].average_margin == pytest.approx(400.0)


# ---------------------------------------------------------- dca is not assumed
def test_dca_is_not_assumed_to_help():
    """With nothing to separate the arms, the recommendation stays NO_DCA."""
    report = research().run(arms={"NO_DCA": series(150, mean=0.0004, seed=1),
                                  "DCA_1": series(150, mean=0.00041, seed=2, start=1000,
                                                  dca_levels=1)})
    assert report.arms["DCA_1"].verdict is DCAVerdict.NO_IMPROVEMENT
    assert report.recommended == "NO_DCA"


def test_a_genuinely_better_arm_is_accepted():
    report = research(minimum_samples=100).run(
        arms={"NO_DCA": series(150, mean=0.0002, seed=1),
              "DCA_1": series(150, mean=0.0009, seed=2, start=1000, dca_levels=1)})
    assert report.arms["DCA_1"].verdict is DCAVerdict.IMPROVES
    assert report.recommended == "DCA_1"


def test_a_clearly_worse_arm_is_harmful():
    report = research(minimum_samples=100).run(
        arms={"NO_DCA": series(150, mean=0.0009, seed=1),
              "DCA_2": series(150, mean=0.0001, seed=2, start=1000, dca_levels=2)})
    assert report.arms["DCA_2"].verdict is DCAVerdict.HARMFUL
    assert "DCA_2" in report.rejected


def test_a_thin_arm_is_insufficient_data():
    report = research(minimum_samples=100).run(
        arms={"NO_DCA": series(150, seed=1),
              "DCA_3": series(5, seed=2, start=1000, dca_levels=3)})
    assert report.arms["DCA_3"].verdict is DCAVerdict.INSUFFICIENT_DATA


def test_the_baseline_arm_is_never_its_own_improvement():
    report = research().run(arms={"NO_DCA": symmetric()})
    assert report.arms["NO_DCA"].verdict is DCAVerdict.NO_IMPROVEMENT


def test_the_report_states_the_rejection_rule():
    report = research().run(arms={"NO_DCA": symmetric()})
    assert "tail risk" in report.as_dict()["note"]


# ------------------------------------------------- spacing and exposure
def test_spacing_is_read_from_the_observation_not_assumed():
    rows = [observation(index, net=0.0004,
                        context={"dca_spacing": 0.0015 if index % 2 else 0.0030})
            for index in range(40)]
    payload = research().by_spacing(rows)
    assert set(payload["spacing"]) == {"0.0015", "0.003"}
    assert "never assumed" in payload["note"]


def test_exposure_limits_are_grouped_from_the_observation():
    rows = [observation(index, net=0.0004, context={"exposure_limit": 0.02})
            for index in range(40)]
    payload = research().by_exposure(rows)
    assert "0.02" in payload["exposure"]
    assert payload["exposure"]["0.02"]["sample_size"] == 40
