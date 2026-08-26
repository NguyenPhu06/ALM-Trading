"""The Phase 11 EXECUTION kill switch.

Distinct from the paper engine's GlobalKillSwitch, which is covered by
tests/test_kill_switch.py and is unchanged.
"""
import pytest

from database.models import KillSwitchEventRecord
from execution.mt5.kill_switch import (
    DCA_BLOCKED,
    NEW_ENTRY_BLOCKED,
    ExecutionKillSwitch,
    ExecutionState,
)
from execution.mt5.order_request import ExecutionIntent
from execution.mt5.order_result import RejectionReason
from tests.phase11_helpers import context, guard_for, order, service_for


def test_it_ships_engaged_so_execution_ships_blocked():
    switch = ExecutionKillSwitch()
    assert switch.engaged and switch.state is ExecutionState.DISABLED
    assert switch.status()["execution"] == "EXECUTION_BLOCKED"


def test_engaged_blocks_both_new_entry_and_dca():
    switch = ExecutionKillSwitch(engaged=True)
    assert not switch.permits(new_entry=True)
    assert not switch.permits(new_entry=False, increases_exposure=True)
    assert NEW_ENTRY_BLOCKED in switch.blocking_reasons(new_entry=True)
    assert DCA_BLOCKED in switch.blocking_reasons(new_entry=False, increases_exposure=True)


def test_released_permits_everything_the_other_checks_allow():
    switch = ExecutionKillSwitch(engaged=False)
    assert switch.state is ExecutionState.ENABLED
    assert switch.permits(new_entry=True)
    assert switch.permits(new_entry=False, increases_exposure=True)
    assert switch.blocking_reasons(new_entry=True) == ()
    assert switch.status()["execution"] == "EXECUTION_ENABLED"


def test_it_never_releases_itself():
    """No timeout, no retry counter, no automatic recovery."""
    switch = ExecutionKillSwitch(engaged=True)
    for _ in range(50):
        switch.permits(new_entry=True)
        switch.blocking_reasons(new_entry=True)
        switch.status()
    assert switch.engaged, "the switch must never release on its own"
    assert switch.status()["auto_release"] is False


def test_releasing_requires_a_reason():
    switch = ExecutionKillSwitch(engaged=True)
    for empty in ("", "   ", None):
        with pytest.raises(ValueError, match="requires a reason"):
            switch.release(empty)
    assert switch.engaged


def test_engage_and_release_are_both_recorded():
    switch = ExecutionKillSwitch(engaged=True)
    switch.release("verified demo account", actor="operator")
    switch.engage("end of test window", actor="operator")
    reasons = [event.reason for event in switch.events]
    assert reasons == ["DEFAULT_ENGAGED", "verified demo account", "end of test window"]
    assert switch.events[-1].state is ExecutionState.DISABLED


def test_engaging_an_already_engaged_switch_is_permitted():
    switch = ExecutionKillSwitch(engaged=True)
    switch.engage("belt and braces")
    assert switch.engaged and len(switch.events) == 2


def test_the_guard_refuses_while_engaged():
    guard = guard_for(engaged=True)
    decision = guard.evaluate(order(), context())
    assert not decision.approved
    assert RejectionReason.KILL_SWITCH_ENGAGED in decision.reasons


def test_the_guard_refuses_dca_while_engaged():
    guard = guard_for(engaged=True)
    decision = guard.evaluate(order(intent=ExecutionIntent.DCA), context())
    assert RejectionReason.KILL_SWITCH_ENGAGED in decision.reasons


def test_engaging_through_the_service_persists_an_event(db_session):
    service, fake = service_for(db_session)
    status = service.engage_kill_switch("operator halt")
    assert status["execution"] == "EXECUTION_BLOCKED"
    rows = db_session.query(KillSwitchEventRecord).all()
    assert rows and rows[-1].reason == "operator halt" and rows[-1].engaged is True

    outcome = service.execute(order())
    assert not outcome.executed and fake.sent == []


def test_releasing_through_the_service_persists_an_event_and_reopens(db_session):
    service, fake = service_for(db_session)
    service.engage_kill_switch("halt")
    service.release_kill_switch("verified demo, resuming manual test")
    rows = db_session.query(KillSwitchEventRecord).all()
    assert [row.engaged for row in rows] == [True, False]
    assert service.execute(order()).executed
    assert len(fake.sent) == 1


def test_a_kill_switch_transition_raises_an_alert(db_session):
    from database.models import DashboardAlertRecord

    service, _ = service_for(db_session)
    service.engage_kill_switch("alert check")
    rows = db_session.query(DashboardAlertRecord).all()
    assert any(row.alert_type == "KILL_SWITCH_TRIGGERED" for row in rows)
    assert any(row.severity == "CRITICAL" for row in rows)


def test_the_paper_kill_switch_is_a_separate_object():
    """Phase 8's switch governs simulation; this one governs DEMO execution."""
    from paper import GlobalKillSwitch

    assert GlobalKillSwitch is not ExecutionKillSwitch
    paper_switch = GlobalKillSwitch()
    assert paper_switch.enabled is False          # paper default: not engaged
    assert ExecutionKillSwitch().engaged is True  # execution default: engaged
