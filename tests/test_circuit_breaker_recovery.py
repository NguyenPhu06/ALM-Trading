"""Recovery after the circuit breaker (section 23).

    "DEMO_AUTOMATED must NOT automatically restart."

Four things are required before the breaker closes: a health check, a risk check,
account validation and human approval. None of them is inferred, and there is no
path in the code that satisfies any of them on its own.
"""
import pytest

from database.models import CircuitBreakerEventRecord
from database.repositories.validation import ValidationRepository
from validation.circuit_breaker import (
    RECOVERY_CHECKS, BreakerSignals, BreakerState, BreakerTrigger, RecoveryChecklist,
    RecoveryRefused,
)
from tests.phase16_helpers import live_context, order, service_for
from tests.phase17_helpers import breaker, full_checklist


def tripped(**kwargs):
    live = breaker(**kwargs)
    live.check(BreakerSignals(daily_drawdown=0.50))
    return live


# --------------------------------------------------------------- the checklist
def test_all_four_declared_checks_are_required():
    assert set(RECOVERY_CHECKS) == {"health_check", "risk_check", "account_validation",
                                    "human_approval"}


def test_an_empty_checklist_is_incomplete():
    checklist = RecoveryChecklist()
    assert checklist.complete is False
    assert set(checklist.missing) == set(RECOVERY_CHECKS)


def test_a_full_checklist_is_complete():
    assert full_checklist().complete is True


@pytest.mark.parametrize("override,missing", [
    (dict(health_check=False), "health_check"),
    (dict(risk_check=False), "risk_check"),
    (dict(account_validation=False), "account_validation"),
    (dict(approved_by=None), "human_approval"),
    (dict(reason=None), "human_approval"),
])
def test_each_missing_check_is_named(override, missing):
    checklist = full_checklist(**override)
    assert checklist.complete is False and missing in checklist.missing


def test_human_approval_needs_both_a_name_and_a_reason():
    assert RecoveryChecklist(approved_by="Phu", reason="").human_approval is False
    assert RecoveryChecklist(approved_by="  ", reason="ok").human_approval is False
    assert RecoveryChecklist(approved_by="Phu", reason="ok").human_approval is True


# ------------------------------------------------------------------ the reset
def test_a_complete_checklist_closes_the_breaker():
    live = tripped()
    event = live.reset(full_checklist())
    assert live.state is BreakerState.CLOSED and live.open is False
    assert event.checklist.complete is True


@pytest.mark.parametrize("override", [
    dict(health_check=False), dict(risk_check=False),
    dict(account_validation=False), dict(approved_by=None),
])
def test_an_incomplete_checklist_refuses_the_reset(override):
    live = tripped()
    with pytest.raises(RecoveryRefused):
        live.reset(full_checklist(**override))
    assert live.open is True, "a refused recovery leaves the breaker open"


def test_the_refusal_names_what_is_missing():
    live = tripped()
    with pytest.raises(RecoveryRefused) as error:
        live.reset(RecoveryChecklist(health_check=True))
    assert set(error.value.missing) == {"risk_check", "account_validation", "human_approval"}


def test_the_reset_records_who_approved_it():
    live = tripped()
    event = live.reset(full_checklist(approved_by="Phu"))
    assert event.actor == "Phu"
    assert event.checklist.approved_by == "Phu"


def test_recovery_clears_the_triggers():
    live = tripped()
    live.reset(full_checklist())
    assert live.triggers == () and live.blocking_reasons() == ()


def test_the_status_states_what_recovery_requires():
    assert set(tripped().status()["recovery_requires"]) == set(RECOVERY_CHECKS)


# ------------------------------------------------- no automatic restart
def test_the_breaker_does_not_close_on_healthy_signals():
    live = tripped()
    for _ in range(10):
        live.check(BreakerSignals())
    assert live.open is True


def test_demo_automated_does_not_resume_by_waiting(db_session):
    """The property section 23 is really asking for."""
    service, fake = service_for(db_session)
    service.breaker.check(BreakerSignals(daily_drawdown=0.50))

    for index in range(3):
        request = order(signal_id=f"signal-{index}")
        outcome = service.submit(request, live_context(service, request))
        assert not outcome.executed
    assert fake.sent == []


def test_after_recovery_execution_is_possible_again(db_session):
    service, fake = service_for(db_session)
    service.breaker.check(BreakerSignals(daily_drawdown=0.50))
    service.breaker.reset(full_checklist())
    # The breaker engaged the kill switch; recovery does not release it for you.
    service.release_kill_switch("verified healthy after recovery")

    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.executed and len(fake.sent) == 1


def test_recovery_alone_does_not_release_the_kill_switch(db_session):
    """Two mechanisms, two deliberate actions."""
    service, fake = service_for(db_session)
    service.breaker.check(BreakerSignals(daily_drawdown=0.50))
    assert service.kill_switch.engaged is True

    service.breaker.reset(full_checklist())
    assert service.kill_switch.engaged is True

    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert not outcome.executed and fake.sent == []


# ---------------------------------------------------------------- persistence
def test_the_recovery_persists_with_its_checklist(db_session):
    repository = ValidationRepository(db_session)
    live = tripped(repository=repository)
    live.reset(full_checklist())

    rows = db_session.query(CircuitBreakerEventRecord).order_by(
        CircuitBreakerEventRecord.id).all()
    assert [row.state for row in rows] == ["OPEN", "CLOSED"]
    recovery = rows[-1]
    assert recovery.health_check and recovery.risk_check
    assert recovery.account_validation and recovery.human_approval
    assert recovery.positions_closed is False


def test_the_recovery_raises_an_alert(db_session):
    from database.models import DashboardAlertRecord
    from database.repositories import AlertRepository
    from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter

    router = AlertRouter(AlertEngine(AlertRepositoryNotificationProvider(
        AlertRepository(db_session))))
    live = tripped(alerts=router)
    live.reset(full_checklist())
    types = {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}
    assert {"CIRCUIT_BREAKER_TRIPPED", "CIRCUIT_BREAKER_RECOVERED"} <= types


# ------------------------------------------------------------------ the API
def test_the_reset_endpoint_refuses_an_incomplete_checklist(client):
    response = client.post("/validation/circuit-breaker/reset", json={
        "health_check": True, "risk_check": False, "account_validation": True,
        "approved_by": "Phu", "reason": "looks fine to me"})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "RECOVERY_INCOMPLETE" and "risk_check" in detail["missing"]


def test_the_reset_endpoint_requires_a_named_human(client):
    response = client.post("/validation/circuit-breaker/reset", json={
        "health_check": True, "risk_check": True, "account_validation": True,
        "approved_by": "P", "reason": "ok"})
    assert response.status_code == 422


def test_the_reset_endpoint_never_resumes_automation(client):
    response = client.post("/validation/circuit-breaker/reset", json={
        "health_check": True, "risk_check": True, "account_validation": True,
        "approved_by": "Phu", "reason": "verified healthy after recovery"})
    assert response.status_code == 200
    assert response.json()["demo_automated_resumed"] is False
