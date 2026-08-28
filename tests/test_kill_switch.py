from paper import GlobalKillSwitch,PaperRiskEngine
def test_kill_switch_blocks_entry_but_permits_safe_management():
    switch=GlobalKillSwitch();switch.activate();engine=PaperRiskEngine(kill_switch=switch)
    assert not engine.evaluate(new_entry=True).allowed and engine.evaluate(new_entry=False).allowed


# ------------------------------------------ Phase 16: the execution kill switch
# Section 16: the switch blocks NEW orders immediately, is reachable from the API,
# the dashboard and configuration, and never closes an open position by itself.
import pytest

from execution.demo.gates import KILL_SWITCH_ENGAGED
from execution.mt5.kill_switch import ExecutionKillSwitch
from tests import phase16_helpers as p16


def test_the_switch_ships_engaged():
    from config.settings import Settings

    assert Settings(**p16.BASE).execution_kill_switch is True


def test_an_engaged_switch_blocks_a_new_order():
    decision = p16.chain_for(p16.armed(), engaged=True).evaluate(p16.order(), p16.context())
    assert not decision.approved
    assert KILL_SWITCH_ENGAGED in decision.reasons
    assert "KillSwitch" in decision.blocked_by


def test_a_released_switch_lets_a_clean_order_through():
    decision = p16.chain_for(p16.armed(), engaged=False).evaluate(p16.order(), p16.context())
    assert decision.approved


def test_the_switch_blocks_immediately_mid_session(db_session):
    service, fake = p16.service_for(db_session)
    first = p16.order(signal_id="signal-001")
    assert service.submit(first, p16.live_context(service, first)).executed

    service.engage_kill_switch("operator stopped trading", actor="Phu")
    second = p16.order(signal_id="signal-002")
    outcome = service.submit(second, p16.live_context(service, second))

    assert not outcome.approved and KILL_SWITCH_ENGAGED in outcome.reasons
    assert len(fake.sent) == 1


def test_engaging_the_switch_does_not_close_open_positions(db_session):
    service, fake = p16.service_for(db_session)
    request = p16.order()
    outcome = service.submit(request, p16.live_context(service, request))
    ticket = outcome.result.broker_ticket

    service.engage_kill_switch("operator stopped trading")
    assert service.client.get_position(ticket) is not None
    assert len(fake.sent) == 1, "no closing order may be sent"


def test_releasing_requires_a_reason(db_session):
    service, _ = p16.service_for(db_session)
    with pytest.raises(ValueError):
        service.release_kill_switch("")


def test_the_switch_never_releases_itself():
    switch = ExecutionKillSwitch(engaged=True, reason="CONFIG_DEFAULT")
    for _ in range(5):
        assert not switch.permits(new_entry=True)
    assert switch.engaged and switch.status()["auto_release"] is False


def test_the_switch_state_is_on_the_dashboard_payload(db_session):
    service, _ = p16.service_for(db_session)
    service.engage_kill_switch("operator stopped trading")
    status = service.status()
    assert status["kill_switch"]["engaged"] is True
    assert "KILL_SWITCH_ENGAGED" in status["blocked_by"]
    assert status["execution_state"] == "EXECUTION_BLOCKED"
