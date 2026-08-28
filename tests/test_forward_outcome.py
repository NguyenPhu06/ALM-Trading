"""Forward outcome resolution (section 6).

The rule the whole module exists for: no outcome before the horizon elapses.
"""
from datetime import timedelta

import pytest

from ai.dataset.labels import LabelingEngine
from ai.edge.evidence import EvidenceSource
from observation.outcome import ForwardOutcomeEngine, OutcomeRefusal
from tests.phase14_helpers import NOW, candles, observation

LATER = NOW + timedelta(hours=1, minutes=1)


def engine(**kwargs):
    return ForwardOutcomeEngine(**kwargs)


def window(drift: float = 0.00006, count: int = 14):
    return candles(count, start=NOW, step_minutes=5, drift=drift)


# ------------------------------------------------------- refusing to be early
def test_an_outcome_is_refused_before_the_horizon_elapses():
    result = engine().resolve(observation(), window(), now=NOW + timedelta(minutes=30))
    assert not result.ok
    assert result.refusal is OutcomeRefusal.HORIZON_NOT_REACHED


def test_an_outcome_is_refused_when_the_window_stops_short():
    short = candles(3, start=NOW, step_minutes=5)
    result = engine().resolve(observation(), short, now=LATER)
    assert result.refusal is OutcomeRefusal.HORIZON_NOT_REACHED


def test_an_outcome_is_refused_with_no_future_data():
    result = engine().resolve(observation(), [], now=LATER)
    assert result.refusal is OutcomeRefusal.NO_FUTURE_DATA


def test_a_wait_observation_has_no_outcome_to_measure():
    result = engine().resolve(observation(direction="WAIT"), window(), now=LATER)
    assert result.refusal is OutcomeRefusal.NOT_DIRECTIONAL


def test_a_missing_entry_price_is_refused():
    result = engine().resolve(observation(price=None), window(), now=LATER)
    assert result.refusal is OutcomeRefusal.NO_ENTRY_PRICE


def test_an_unknown_horizon_is_refused():
    result = engine().resolve(observation(horizon="7y"), window(), now=LATER)
    assert result.refusal is OutcomeRefusal.UNKNOWN_HORIZON


def test_candles_after_the_deadline_are_ignored():
    """A window that runs long must not extend the measurement period."""
    long_window = candles(60, start=NOW, step_minutes=5, drift=0.00006)
    short = engine().resolve(observation(), window(), now=LATER).outcome
    long = engine().resolve(observation(), long_window, now=LATER).outcome
    assert short.future_price == pytest.approx(long.future_price)
    assert long.bars == short.bars


# ------------------------------------------------------- 6. the outcome itself
def test_the_outcome_carries_every_documented_field():
    payload = engine().resolve(observation(), window(), now=LATER).outcome.as_dict()
    for field in ("future_price", "future_return", "mfe", "mae",
                  "maximum_favorable_excursion", "maximum_adverse_excursion",
                  "hypothetical_pnl", "holding_time", "spread", "estimated_cost",
                  "net_hypothetical_pnl"):
        assert field in payload, field


def test_a_rising_market_is_a_gain_for_a_buy():
    outcome = engine().resolve(observation(direction="BUY"), window(0.00006),
                               now=LATER).outcome
    assert outcome.future_return > 0
    assert outcome.actual_direction == "UP"


def test_a_rising_market_is_a_loss_for_a_sell():
    """Return is signed by the observed direction; actual_direction is not."""
    outcome = engine().resolve(observation(direction="SELL"), window(0.00006),
                               now=LATER).outcome
    assert outcome.future_return < 0, "the SELL lost money"
    assert outcome.actual_direction == "UP", "the market still went up"
    assert outcome.predicted_direction == "DOWN"


def test_a_winning_sell_is_not_reported_as_an_up_market():
    """The market direction must not be inferred from a direction-signed return."""
    outcome = engine().resolve(observation(direction="SELL"), window(-0.00006),
                               now=LATER).outcome
    assert outcome.future_return > 0, "the SELL made money"
    assert outcome.actual_direction == "DOWN"
    assert outcome.predicted_direction == outcome.actual_direction


def test_a_falling_market_is_a_gain_for_a_sell():
    outcome = engine().resolve(observation(direction="SELL"), window(-0.00006),
                               now=LATER).outcome
    assert outcome.future_return > 0


def test_mfe_is_favourable_and_mae_is_adverse():
    outcome = engine().resolve(observation(), window(), now=LATER).outcome
    assert outcome.mfe >= outcome.future_return
    assert outcome.mae <= 0
    assert outcome.maximum_favorable_excursion == outcome.mfe
    assert outcome.maximum_adverse_excursion == outcome.mae


def test_the_holding_time_is_the_horizon():
    outcome = engine().resolve(observation(horizon="1h"), window(), now=LATER).outcome
    assert outcome.holding_time == pytest.approx(3600.0)


def test_the_outcome_resolves_at_the_deadline_not_at_now():
    outcome = engine().resolve(observation(), window(), now=NOW + timedelta(days=3)).outcome
    assert outcome.resolved_at == NOW + timedelta(hours=1)


def test_the_outcome_is_forward_observation_evidence():
    outcome = engine().resolve(observation(), window(), now=LATER).outcome
    assert outcome.evidence is EvidenceSource.FORWARD_OBSERVATION


def test_a_label_is_attached_when_a_labeler_is_supplied():
    result = engine(labeler=LabelingEngine()).resolve(observation(), window(), now=LATER)
    assert result.outcome.label is not None
    assert result.outcome.label.horizon == "1h"


def test_no_labeler_means_no_label_not_a_guess():
    result = engine().resolve(observation(), window(), now=LATER)
    assert result.outcome.label is None


def test_the_number_of_bars_used_is_recorded():
    outcome = engine().resolve(observation(), window(count=14), now=LATER).outcome
    assert outcome.bars == 12  # 12 five-minute bars fit inside one hour
