"""Forward labelling: horizons, targets and trading costs."""
from datetime import timedelta

import pytest

from ai.dataset.labels import (
    Direction, HORIZONS, LabelRefusal, LabelingEngine, Outcome, TradingCosts,
    resolve_horizon,
)
from tests.phase13_helpers import NOW, candles


def engine(**kwargs):
    return LabelingEngine(**kwargs)


def window(*, drift=0.00010, count=24, start=None, step=5):
    return candles(count, start=start or (NOW - timedelta(hours=3)), step_minutes=step,
                   drift=drift)


def test_every_documented_horizon_resolves():
    for name in ("5m", "15m", "30m", "1h", "2h", "4h", "8h", "24h"):
        assert resolve_horizon(name) == HORIZONS[name]


def test_an_unknown_horizon_is_refused():
    entry = NOW - timedelta(hours=3)
    result = engine().label(entry_price=1.1, entry_time=entry, future=window(), horizon="7m")
    assert result.refusal is LabelRefusal.UNKNOWN_HORIZON


def test_a_label_is_refused_before_its_horizon_elapses():
    """The central rule: no label until the horizon has fully passed."""
    entry = NOW - timedelta(minutes=20)
    future = candles(4, start=entry, step_minutes=5, drift=0.0001)
    result = engine().label(entry_price=1.1, entry_time=entry, future=future,
                            horizon="1h", now=NOW)
    assert not result.ok and result.refusal is LabelRefusal.HORIZON_NOT_ELAPSED


def test_a_truncated_window_is_refused_even_after_the_horizon():
    """A window that stops short would produce an optimistic, contaminated label."""
    entry = NOW - timedelta(hours=4)
    future = candles(3, start=entry, step_minutes=5, drift=0.0001)   # only 15 minutes
    result = engine().label(entry_price=1.1, entry_time=entry, future=future,
                            horizon="1h", now=NOW)
    assert not result.ok and result.refusal is LabelRefusal.HORIZON_NOT_ELAPSED


def test_no_future_data_is_refused():
    entry = NOW - timedelta(hours=4)
    result = engine().label(entry_price=1.1, entry_time=entry, future=[],
                            horizon="1h", now=NOW)
    assert result.refusal is LabelRefusal.NO_FUTURE_DATA


def test_an_invalid_entry_is_refused():
    entry = NOW - timedelta(hours=4)
    result = engine().label(entry_price=0, entry_time=entry, future=window(), horizon="1h",
                            now=NOW)
    assert result.refusal is LabelRefusal.INVALID_ENTRY


def test_a_rising_market_labels_up():
    entry = NOW - timedelta(hours=4)
    result = engine().label(entry_price=1.1000, entry_time=entry,
                            future=window(drift=0.00020, start=entry), horizon="1h", now=NOW)
    assert result.ok and result.label.direction is Direction.UP


def test_a_falling_market_labels_down():
    entry = NOW - timedelta(hours=4)
    result = engine().label(entry_price=1.1000, entry_time=entry,
                            future=window(drift=-0.00020, start=entry), horizon="1h", now=NOW)
    assert result.label.direction is Direction.DOWN


def test_a_flat_market_labels_neutral():
    entry = NOW - timedelta(hours=4)
    result = engine(classification_threshold=0.01).label(
        entry_price=1.1000, entry_time=entry, future=window(drift=0.00001, start=entry),
        horizon="1h", now=NOW)
    assert result.label.direction is Direction.NEUTRAL


def test_every_regression_target_is_produced():
    entry = NOW - timedelta(hours=4)
    label = engine().label(entry_price=1.1000, entry_time=entry,
                           future=window(drift=0.00015, start=entry), horizon="1h",
                           now=NOW).label
    for name in ("future_return", "future_mfe", "future_mae", "future_volatility",
                 "future_max_return", "future_max_drawdown"):
        assert getattr(label, name) is not None, name


def test_mfe_is_at_least_the_return_and_mae_is_not_positive():
    entry = NOW - timedelta(hours=4)
    label = engine().label(entry_price=1.1000, entry_time=entry,
                           future=window(drift=0.00015, start=entry), horizon="1h",
                           now=NOW).label
    assert label.future_mfe >= label.future_return
    assert label.future_mae <= 0


def test_time_to_event_targets_are_produced():
    entry = NOW - timedelta(hours=4)
    label = engine().label(entry_price=1.1000, entry_time=entry,
                           future=window(drift=0.00030, start=entry), horizon="1h",
                           now=NOW).label
    assert label.time_to_profit is not None and label.time_to_profit > 0
    assert label.time_to_max_adverse is not None


def test_costs_are_subtracted_from_the_gross_move():
    entry = NOW - timedelta(hours=4)
    label = engine().label(entry_price=1.1000, entry_time=entry,
                           future=window(drift=0.00015, start=entry), horizon="1h",
                           spread=0.00012, now=NOW).label
    assert label.costs > 0
    assert label.net_return == pytest.approx(label.future_return - label.costs, abs=1e-9)


def test_a_move_that_does_not_clear_costs_is_unprofitable():
    """A tiny positive move is not a win once spread and slippage are paid."""
    entry = NOW - timedelta(hours=4)
    tiny = [{"timestamp": entry + timedelta(minutes=5 * (index + 1)), "open": 1.1000,
             "high": 1.10004, "low": 1.09998, "close": 1.10002} for index in range(20)]
    label = engine().label(entry_price=1.1000, entry_time=entry, future=tiny,
                           horizon="1h", spread=0.00050, now=NOW).label
    assert label.future_return > 0
    assert label.net_return < 0
    assert label.outcome is Outcome.UNPROFITABLE


def test_a_move_that_clears_costs_is_profitable():
    entry = NOW - timedelta(hours=4)
    label = engine().label(entry_price=1.1000, entry_time=entry,
                           future=window(drift=0.00030, start=entry), horizon="1h",
                           spread=0.00005, now=NOW).label
    assert label.outcome is Outcome.PROFITABLE


def test_a_wider_spread_can_flip_the_outcome():
    entry = NOW - timedelta(hours=4)
    future = window(drift=0.00004, start=entry)
    cheap = engine().label(entry_price=1.1000, entry_time=entry, future=future,
                           horizon="1h", spread=0.00001, now=NOW).label
    expensive = engine().label(entry_price=1.1000, entry_time=entry, future=future,
                               horizon="1h", spread=0.00200, now=NOW).label
    assert cheap.outcome is Outcome.PROFITABLE
    assert expensive.outcome is Outcome.UNPROFITABLE


def test_swap_is_charged_for_the_holding_period():
    costs = TradingCosts(spread=0.0001, slippage=0.0, commission=0.0, swap_per_day=0.001)
    assert costs.total(holding=timedelta(days=1)) > costs.total(holding=timedelta(hours=1))


def test_a_short_direction_inverts_the_labels():
    entry = NOW - timedelta(hours=4)
    future = window(drift=-0.00020, start=entry)
    long_label = engine(direction="LONG").label(entry_price=1.1000, entry_time=entry,
                                                future=future, horizon="1h", now=NOW).label
    short_label = engine(direction="SHORT").label(entry_price=1.1000, entry_time=entry,
                                                  future=future, horizon="1h", now=NOW).label
    assert long_label.direction is Direction.DOWN
    assert short_label.direction is Direction.UP


def test_the_resolved_timestamp_is_the_horizon_deadline():
    entry = NOW - timedelta(hours=4)
    label = engine().label(entry_price=1.1000, entry_time=entry,
                           future=window(start=entry), horizon="1h", now=NOW).label
    assert label.resolved_at == entry + timedelta(hours=1)


def test_multiple_horizons_can_be_labelled_at_once():
    entry = NOW - timedelta(hours=6)
    future = window(count=80, start=entry, drift=0.00010)
    results = engine().label_many(entry_price=1.1000, entry_time=entry, future=future,
                                  horizons=["15m", "30m", "1h"], now=NOW)
    assert set(results) == {"15m", "30m", "1h"}
    assert all(result.ok for result in results.values())
