"""DCA validation (section 14).

DCA stays disabled by default, and this module does not change that. The
decisive rule, implemented literally: **reject DCA if the increased win rate is
achieved only through materially increased tail risk.** Winning more often while
losing far more when you lose is not an improvement.
"""
import pytest

from validation.dca_validation import DCAValidator, DCAVerdict
from tests.phase16_helpers import armed, settings


def validator(**kwargs):
    kwargs.setdefault("minimum_samples", 10)
    kwargs.setdefault("tail_tolerance", 0.20)
    return DCAValidator(**kwargs)


def arm(count, *, win_rate=0.6, win=1.0, loss=-1.0, mae=-0.001, mfe=0.002):
    wins = int(round(count * win_rate))
    return [{"net_pnl": win if index < wins else loss, "mae": mae, "mfe": mfe}
            for index in range(count)]


def laddered(count=20, levels=3):
    """Trades with an initial entry plus `levels` DCA entries each."""
    rows = []
    for index in range(count):
        entries = [{"level": level, "price": 1.10 - 0.001 * level, "volume": 0.02,
                    "exposure": 2200.0, "risk": 50.0, "mae": -0.001 * (level + 1),
                    "mfe": 0.002}
                   for level in range(levels + 1)]
        rows.append({"net_pnl": 1.0 if index % 2 else -1.0, "entries": entries,
                     "mae": -0.003, "mfe": 0.002})
    return rows


# ---------------------------------------------------------------- off by default
def test_dca_is_disabled_by_default():
    assert settings().demo_dca_enabled is False
    assert armed().demo_dca_enabled is False


def test_a_disabled_dca_with_no_trades_reports_disabled():
    report = validator().evaluate([], [], enabled=False)
    assert report.verdict is DCAVerdict.DISABLED
    assert "DCA_DISABLED" in report.reasons
    assert report.recommended == "NO_DCA"


def test_the_validator_reads_the_setting_when_not_told():
    live = DCAValidator(minimum_samples=10, settings=settings())
    assert live.evaluate([], []).verdict is DCAVerdict.DISABLED


# ---------------------------------------------------------------- the levels
def test_every_level_is_tracked_independently():
    """Section 14: initial entry plus DCA 1, 2 and 3."""
    levels = validator().levels(laddered(count=5, levels=3))
    assert [level.level for level in levels] == [0, 1, 2, 3]
    assert all(level.entries == 5 for level in levels)


def test_each_level_reports_its_own_exposure_and_risk():
    levels = validator().levels(laddered(count=5, levels=2))
    assert levels[0].exposure == pytest.approx(5 * 2200.0)
    assert levels[0].risk == pytest.approx(5 * 50.0)


def test_each_level_reports_its_own_excursions():
    levels = validator().levels(laddered(count=5, levels=2))
    assert levels[0].mae == pytest.approx(-0.001)
    assert levels[2].mae == pytest.approx(-0.003)


def test_the_aggregate_exposure_and_risk_are_summed():
    report = validator().evaluate(laddered(count=20, levels=2), arm(20), enabled=True)
    assert report.aggregate_exposure == pytest.approx(20 * 3 * 2200.0)
    assert report.aggregate_risk == pytest.approx(20 * 3 * 50.0)


# ---------------------------------------------------------------- vs NO_DCA
def test_a_small_sample_is_insufficient_data():
    report = validator().evaluate(arm(3), arm(3), enabled=True)
    assert report.verdict is DCAVerdict.INSUFFICIENT_DATA
    assert "INSUFFICIENT_SAMPLES" in report.reasons


def test_a_worse_expectancy_is_harmful():
    report = validator().evaluate(arm(20, win_rate=0.3), arm(20, win_rate=0.7), enabled=True)
    assert report.verdict is DCAVerdict.HARMFUL
    assert "EXPECTANCY_WORSE_THAN_NO_DCA" in report.reasons
    assert report.recommended == "NO_DCA"


def test_a_win_rate_bought_with_tail_risk_is_rejected():
    """The decisive case in the spec."""
    # DCA wins more often, but its losses are far larger.
    dca = arm(20, win_rate=0.9, win=1.0, loss=-20.0)
    flat = arm(20, win_rate=0.5, win=1.0, loss=-1.0)
    report = validator().evaluate(dca, flat, enabled=True)

    assert report.win_rate_delta > 0, "DCA does win more often"
    assert report.verdict is DCAVerdict.REJECTED_TAIL_RISK
    assert "WIN_RATE_BOUGHT_WITH_TAIL_RISK" in report.reasons
    assert report.recommended == "NO_DCA"


def test_a_better_expectancy_does_not_excuse_a_worse_tail():
    """Same win rate, higher expectancy, far worse worst case. Still rejected."""
    dca = arm(20, win_rate=0.5, win=12.0, loss=-8.0)
    flat = arm(20, win_rate=0.5, win=1.0, loss=-1.0)
    report = validator().evaluate(dca, flat, enabled=True)

    assert report.expectancy_delta > 0
    assert report.verdict is DCAVerdict.REJECTED_TAIL_RISK
    assert "TAIL_RISK_MATERIALLY_WORSE" in report.reasons


def test_a_win_rate_gain_with_a_worse_expectancy_still_names_the_tail():
    dca = arm(20, win_rate=0.9, win=1.0, loss=-20.0)
    flat = arm(20, win_rate=0.5, win=1.0, loss=-1.0)
    report = validator().evaluate(dca, flat, enabled=True)
    assert report.verdict is DCAVerdict.REJECTED_TAIL_RISK
    assert "EXPECTANCY_WORSE_THAN_NO_DCA" in report.reasons


def test_a_genuine_improvement_is_reported_as_improving():
    dca = arm(20, win_rate=0.7, win=1.0, loss=-1.0)
    flat = arm(20, win_rate=0.5, win=1.0, loss=-1.0)
    report = validator().evaluate(dca, flat, enabled=True)
    assert report.verdict is DCAVerdict.IMPROVES
    assert report.recommended == "DCA"


def test_no_measurable_difference_is_not_proven():
    rows = arm(20, win_rate=0.5)
    report = validator().evaluate(rows, list(rows), enabled=True)
    assert report.verdict is DCAVerdict.NOT_PROVEN
    assert "NO_MEASURABLE_IMPROVEMENT" in report.reasons
    assert report.recommended == "NO_DCA"


def test_the_tail_is_reported_for_both_arms():
    dca = arm(20, win_rate=0.9, win=1.0, loss=-20.0)
    flat = arm(20, win_rate=0.5, win=1.0, loss=-1.0)
    report = validator().evaluate(dca, flat, enabled=True)
    assert report.dca.tail_loss == pytest.approx(-20.0)
    assert report.no_dca.tail_loss == pytest.approx(-1.0)
    assert report.dca.worst_loss == pytest.approx(-20.0)


def test_the_report_states_the_default_recommendation():
    note = validator().evaluate([], [], enabled=False).as_dict()["note"]
    assert "NO_DCA is the default recommendation" in note


# ------------------------------------------------------------- the gate holds
def test_validating_dca_does_not_enable_it():
    config = settings()
    dca = arm(20, win_rate=0.7)
    flat = arm(20, win_rate=0.5)
    report = DCAValidator(minimum_samples=10, settings=config).evaluate(dca, flat, enabled=True)
    assert report.verdict is DCAVerdict.IMPROVES
    assert config.demo_dca_enabled is False, "a favourable finding is not a switch"


def test_the_validator_cannot_change_a_setting():
    for name in ("enable", "arm", "apply", "set"):
        assert not hasattr(DCAValidator, name)
