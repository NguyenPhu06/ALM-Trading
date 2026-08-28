"""Trading sessions (Phase 12 section 10)."""
from datetime import datetime, timezone

import pytest

from features.session import SessionEngine, SessionName
from strategy.session import TradingSessionEngine


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, tzinfo=timezone.utc)


@pytest.mark.parametrize(("hour", "expected"), [
    (2, SessionName.ASIA),
    (9, SessionName.LONDON),
    (14, SessionName.LONDON_NEW_YORK_OVERLAP),
    (20, SessionName.NEW_YORK),
    (23, SessionName.OFF_SESSION),
])
def test_each_session_is_identified(hour, expected):
    assert SessionEngine().session_for(at(hour)) is expected


def test_the_overlap_is_its_own_session():
    """London/New York overlap is reported distinctly, not as one or the other."""
    session = SessionEngine().session_for(at(14))
    assert session is SessionName.LONDON_NEW_YORK_OVERLAP
    assert session not in {SessionName.LONDON, SessionName.NEW_YORK}


def test_session_windows_are_configurable():
    custom = SessionEngine(asia=("00:00", "04:00"), london=("04:00", "08:00"),
                           new_york=("08:00", "12:00"))
    assert custom.session_for(at(5)) is SessionName.LONDON
    assert custom.session_for(at(9)) is SessionName.NEW_YORK


def test_session_context_records_start_end_and_progress():
    context = TradingSessionEngine(timezone="UTC").context(at(9))
    assert context.session is SessionName.LONDON
    assert context.session_start is not None and context.session_end is not None
    assert context.minutes_from_session_open >= 0
    assert context.minutes_to_session_close >= 0


def test_an_off_session_moment_has_no_window():
    context = TradingSessionEngine(timezone="UTC").context(at(23))
    assert context.session is SessionName.OFF_SESSION
    assert context.session_start is None and context.session_end is None


def test_no_session_is_labelled_safe_or_unsafe():
    """The engine reports which session it is, never a verdict about it."""
    context = TradingSessionEngine(timezone="UTC").context(at(14))
    payload = str(context).lower()
    assert "safe" not in payload and "unsafe" not in payload
    assert not hasattr(context, "safe") and not hasattr(context, "tradeable")
