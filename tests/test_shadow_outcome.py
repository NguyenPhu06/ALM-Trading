"""Shadow outcomes (section 4).

What a signal *would* have produced, net of modelled cost. The net figure is the
headline: an expected move smaller than the spread and the estimated slippage is
not an expected profit, and reporting the gross number instead would be the most
flattering possible lie.
"""
from datetime import timedelta

import pytest

from database.models import ShadowOutcomeRecord, ShadowSignalRecord
from database.repositories.validation import ValidationRepository
from validation.shadow import ShadowStatus
from tests.phase16_helpers import LONDON_MOMENT, order
from tests.phase17_helpers import EXIT_MOMENT, recorder, shadow_signal


def resolve(*, exit_price=1.1050, highs=None, lows=None, live=None, signal=None, **kwargs):
    live = live or recorder()
    signal = signal or shadow_signal(recorder_=live)
    return live, signal, live.resolve(signal, exit_price=exit_price, exit_time=EXIT_MOMENT,
                                      highs=highs, lows=lows, **kwargs)


# ------------------------------------------------------------- the arithmetic
def test_a_winning_signal_reports_its_gross_and_net():
    _, _, outcome = resolve(exit_price=1.1050)
    assert outcome.expected_entry == pytest.approx(1.10024)
    assert outcome.expected_exit == pytest.approx(1.1050)
    assert outcome.expected_pnl == pytest.approx(0.00476)
    # Gross minus spread, slippage and commission.
    assert outcome.net_expected_pnl == pytest.approx(0.00476 - 0.00012 - 0.00002, abs=1e-9)


def test_the_net_figure_is_the_one_that_decides_profitability():
    """A move that does not clear cost is not a win."""
    _, _, outcome = resolve(exit_price=1.10029)
    assert outcome.expected_pnl > 0
    assert outcome.net_expected_pnl < 0
    assert outcome.profitable is False


def test_a_sell_signal_profits_when_price_falls():
    live = recorder()
    signal = shadow_signal(request=order(side="SELL", stop_loss=1.11000,
                                         take_profit=1.09000), recorder_=live)
    outcome = live.resolve(signal, exit_price=1.0950, exit_time=EXIT_MOMENT)
    assert outcome.expected_pnl == pytest.approx(0.00524)


def test_the_duration_is_measured_from_the_signal():
    _, _, outcome = resolve()
    assert outcome.duration_seconds == pytest.approx(7200.0)


# -------------------------------------------------------------- excursions
def test_mfe_and_mae_come_from_the_path():
    _, _, outcome = resolve(exit_price=1.1030, highs=[1.1060, 1.1030],
                            lows=[1.0990, 1.1010])
    assert outcome.mfe == pytest.approx(1.1060 - 1.10024)
    assert outcome.mae == pytest.approx(1.0990 - 1.10024)


def test_without_a_path_the_excursions_are_bounded_by_the_exit():
    """Understating them is the safe direction to be wrong in."""
    _, _, outcome = resolve(exit_price=1.1050)
    assert outcome.mfe == pytest.approx(1.1050 - 1.10024)
    assert outcome.mae == pytest.approx(0.0)


def test_a_short_position_measures_excursions_the_other_way():
    live = recorder()
    signal = shadow_signal(request=order(side="SELL", stop_loss=1.11000,
                                         take_profit=1.09000), recorder_=live)
    outcome = live.resolve(signal, exit_price=1.0980, exit_time=EXIT_MOMENT,
                           highs=[1.1030], lows=[1.0950])
    assert outcome.mfe == pytest.approx(1.10024 - 1.0950)
    assert outcome.mae == pytest.approx(1.10024 - 1.1030)


# ---------------------------------------------------------------- lifecycle
def test_resolving_marks_the_signal_resolved():
    live, signal, _ = resolve()
    assert live.get(signal.shadow_signal_id).status is ShadowStatus.RESOLVED


def test_an_unresolved_signal_stays_open():
    live = recorder()
    signal = shadow_signal(recorder_=live)
    assert live.open_signals() == (signal,)


def test_a_signal_with_no_exit_is_abandoned_not_assumed_flat():
    live = recorder()
    signal = shadow_signal(recorder_=live)
    abandoned = live.abandon(signal.shadow_signal_id)
    assert abandoned.status is ShadowStatus.ABANDONED
    assert live.outcome_for(signal.shadow_signal_id) is None


def test_a_non_directional_signal_cannot_be_resolved():
    live = recorder()
    signal = shadow_signal(request=order(side="BUY"), recorder_=live)
    from dataclasses import replace

    flat = replace(signal, side="WAIT")
    assert live.resolve(flat, exit_price=1.10, exit_time=EXIT_MOMENT) is None


def test_a_signal_without_an_entry_cannot_be_resolved():
    live = recorder()
    signal = shadow_signal(request=order(price=None), recorder_=live)
    assert live.resolve(signal, exit_price=1.10, exit_time=EXIT_MOMENT) is None


def test_an_outcome_never_reports_an_order():
    _, _, outcome = resolve()
    assert outcome.as_dict()["orders_sent"] == 0


def test_the_exit_reason_is_carried_through():
    _, _, outcome = resolve(exit_reason="TAKE_PROFIT")
    assert outcome.exit_reason == "TAKE_PROFIT"


# --------------------------------------------------------------- persistence
def test_a_resolved_outcome_persists_with_its_signal(db_session):
    repository = ValidationRepository(db_session)
    live = recorder(repository)
    signal = shadow_signal(recorder_=live)
    live.resolve(signal, exit_price=1.1050, exit_time=EXIT_MOMENT, exit_reason="TAKE_PROFIT")

    outcome_row = db_session.query(ShadowOutcomeRecord).one()
    signal_row = db_session.query(ShadowSignalRecord).one()
    assert outcome_row.shadow_signal_id == signal.shadow_signal_id
    assert outcome_row.net_expected_pnl == pytest.approx(0.00462, abs=1e-6)
    assert signal_row.status == "RESOLVED"


def test_outcomes_can_be_read_back(db_session):
    repository = ValidationRepository(db_session)
    live = recorder(repository)
    live.resolve(shadow_signal(recorder_=live), exit_price=1.1050, exit_time=EXIT_MOMENT)
    assert len(repository.recent_shadow_outcomes()) == 1
