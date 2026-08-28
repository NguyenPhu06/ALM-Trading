"""The trading day and its risk budget (section 24).

The interesting cases are the boundaries. A "daily" loss limit means nothing
until the day is pinned down, so most of this file is about which instants belong
to which trading day under an explicit timezone and reset hour.
"""
from datetime import datetime, timedelta, timezone

import pytest

from database.models import DemoDailyRiskRecord
from database.repositories.demo import DemoTradingRepository
from execution.demo.daily_risk import DailyRiskTracker
from execution.demo.limits import (
    MAX_DAILY_LOSS, MAX_TOTAL_DRAWDOWN, MAX_TRADES_PER_DAY, DemoRiskLimits,
)
from tests.phase16_helpers import armed, chain_for, context, live_context, order, service_for

LIMITS = DemoRiskLimits(max_daily_loss=0.02, max_total_drawdown=0.05, max_trades_per_day=3)


def tracker(**kwargs):
    kwargs.setdefault("limits", LIMITS)
    return DailyRiskTracker(**kwargs)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


# --------------------------------------------------------------- the boundary
def test_the_trading_day_uses_the_configured_timezone():
    """23:00 UTC on the 27th is already the 28th in Tokyo."""
    assert tracker(timezone_name="UTC").trading_day(utc(2026, 8, 27, 23)).isoformat() == "2026-08-27"
    assert tracker(timezone_name="Asia/Tokyo").trading_day(
        utc(2026, 8, 27, 23)).isoformat() == "2026-08-28"


def test_the_reset_hour_moves_the_boundary():
    rolled = tracker(timezone_name="UTC", reset_hour=22)
    assert rolled.trading_day(utc(2026, 8, 27, 21)).isoformat() == "2026-08-26"
    assert rolled.trading_day(utc(2026, 8, 27, 22)).isoformat() == "2026-08-27"


def test_the_day_bounds_are_explicit():
    start, end = tracker(timezone_name="UTC", reset_hour=22).day_bounds(utc(2026, 8, 27, 23))
    assert start == utc(2026, 8, 27, 22) and end == utc(2026, 8, 28, 22)


def test_an_invalid_reset_hour_is_refused():
    with pytest.raises(ValueError, match="reset hour"):
        tracker(reset_hour=24)


def test_a_naive_timestamp_is_treated_as_utc():
    assert tracker().trading_day(datetime(2026, 8, 27, 12)).isoformat() == "2026-08-27"


# ------------------------------------------------------------------ the budget
def test_the_first_update_sets_the_starting_equity():
    state = tracker().update(equity=10_000.0, moment=utc(2026, 8, 27, 8))
    assert state.starting_equity == 10_000.0 and state.daily_pnl == 0.0


def test_daily_pnl_and_drawdown_track_equity():
    live = tracker()
    live.update(equity=10_000.0, moment=utc(2026, 8, 27, 8))
    state = live.update(equity=9_800.0, moment=utc(2026, 8, 27, 12))
    assert state.daily_pnl == pytest.approx(-200.0)
    assert state.daily_loss == pytest.approx(200.0)
    assert state.daily_drawdown == pytest.approx(0.02)


def test_a_profitable_day_reports_no_loss():
    live = tracker()
    live.update(equity=10_000.0, moment=utc(2026, 8, 27, 8))
    state = live.update(equity=10_500.0, moment=utc(2026, 8, 27, 12))
    assert state.daily_loss == 0.0 and state.daily_drawdown == 0.0


def test_crossing_the_boundary_resets_the_budget():
    live = tracker()
    live.update(equity=10_000.0, moment=utc(2026, 8, 27, 8))
    live.record_trade()
    breached = live.update(equity=9_700.0, moment=utc(2026, 8, 27, 20))
    assert breached.blocked and MAX_DAILY_LOSS in breached.reasons

    fresh = live.update(equity=9_700.0, moment=utc(2026, 8, 28, 8))
    assert fresh.trading_day.isoformat() == "2026-08-28"
    assert fresh.starting_equity == 9_700.0 and not fresh.blocked
    assert fresh.trade_count == 0


def test_total_drawdown_spans_days():
    """Peak equity is not a daily figure; a new day does not forgive the drawdown."""
    live = tracker()
    live.update(equity=10_000.0, moment=utc(2026, 8, 27, 8))
    live.update(equity=9_000.0, moment=utc(2026, 8, 28, 8))
    state = live.update(equity=9_000.0, moment=utc(2026, 8, 29, 8))
    assert state.total_drawdown == pytest.approx(0.10)
    assert MAX_TOTAL_DRAWDOWN in state.reasons


def test_the_daily_trade_count_is_limited():
    live = tracker()
    live.update(equity=10_000.0, moment=utc(2026, 8, 27, 8))
    for _ in range(LIMITS.max_trades_per_day):
        live.record_trade()
    state = live.update(equity=10_000.0, moment=utc(2026, 8, 27, 9))
    assert state.blocked and MAX_TRADES_PER_DAY in state.reasons


def test_a_restored_day_keeps_its_budget():
    """A restart must not hand back a fresh daily allowance."""
    live = tracker()
    live.update(equity=10_000.0, moment=utc(2026, 8, 27, 8))
    live.record_trade()
    spent = live.update(equity=9_900.0, moment=utc(2026, 8, 27, 12))

    restarted = tracker()
    restarted.restore(spent)
    state = restarted.update(equity=9_900.0, moment=utc(2026, 8, 27, 13))
    assert state.starting_equity == 10_000.0 and state.trade_count == 1


# -------------------------------------------------------------- the gate hook
def test_a_breached_daily_loss_blocks_an_order():
    from tests.phase16_helpers import daily_state

    breached = daily_state(daily_drawdown=0.05, blocked=True, reasons=(MAX_DAILY_LOSS,))
    decision = chain_for(armed()).evaluate(order(), context(daily=breached))
    assert not decision.approved and MAX_DAILY_LOSS in decision.reasons
    assert "DrawdownGate" in decision.blocked_by


def test_a_missing_day_state_blocks_an_order():
    """Without evidence the budget is intact, the gate refuses."""
    decision = chain_for(armed()).evaluate(order(), context(daily=None))
    assert not decision.approved
    assert "DAILY_RISK_STATE_UNAVAILABLE" in decision.reasons


def test_the_trade_count_limit_blocks_an_order():
    from tests.phase16_helpers import daily_state

    spent = daily_state(trade_count=99, blocked=True, reasons=(MAX_TRADES_PER_DAY,))
    decision = chain_for(armed()).evaluate(order(), context(daily=spent))
    assert not decision.approved and MAX_TRADES_PER_DAY in decision.reasons


# ---------------------------------------------------------------- persistence
def test_the_day_state_persists_and_updates_in_place(db_session):
    repository = DemoTradingRepository(db_session)
    live = tracker()
    repository.save_daily_risk(live.update(equity=10_000.0, moment=utc(2026, 8, 27, 8)))
    repository.save_daily_risk(live.update(equity=9_900.0, moment=utc(2026, 8, 27, 12)))

    rows = db_session.query(DemoDailyRiskRecord).all()
    assert len(rows) == 1, "one row per trading day, updated in place"
    assert rows[0].equity == 9_900.0 and rows[0].daily_pnl == pytest.approx(-100.0)


def test_the_service_counts_a_submitted_order_against_the_day(db_session):
    service, _ = service_for(db_session)
    request = order()
    service.submit(request, live_context(service, request))
    assert service.daily.trade_count == 1
