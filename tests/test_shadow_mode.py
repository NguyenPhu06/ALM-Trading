"""SHADOW mode (sections 1 and 2).

The property this file exists to protect: **shadow trading never sends a broker
order.** Everything else — that the mode is declared, that it sends nothing, that
it still records everything — follows from that.
"""
import pytest
from pydantic import ValidationError

from config.settings import EXECUTION_MODES, Settings
from database.models import ExecutionResultRecord, ShadowSignalRecord
from database.repositories.validation import ValidationRepository
from execution.demo.modes import (
    MODE_DOES_NOT_EXECUTE, SIMULATION_MODES, ExecutionMode, ExecutionModeResolver,
)
from validation.shadow import (
    NOT_EXECUTED_BLOCKED, NOT_EXECUTED_MODE, SHADOW_SOURCE, ShadowRecorder, ShadowStatus,
)
from tests.phase16_helpers import BASE, live_context, order, settings
from tests.phase17_helpers import recorder, shadow_settings, shadow_signal
from tests.phase16_helpers import service_for


# ------------------------------------------------------------------ the mode
def test_shadow_is_a_declared_mode():
    assert "SHADOW" in EXECUTION_MODES
    assert ExecutionMode.SHADOW in SIMULATION_MODES


def test_shadow_never_sends_orders():
    decision = ExecutionModeResolver(shadow_settings()).resolve()
    assert decision.mode is ExecutionMode.SHADOW
    assert decision.sends_orders is False
    assert MODE_DOES_NOT_EXECUTE in decision.reasons


def test_shadow_does_not_enable_live_trading():
    config = shadow_settings()
    assert config.live_trading_enabled is False
    assert config.real_account_execution is False
    assert ExecutionModeResolver(config).resolve().live_enabled is False


def test_shadow_does_not_need_demo_trading_enabled():
    """It reaches no broker, so it needs none of the broker gates open."""
    config = shadow_settings()
    assert config.demo_trading_enabled is False
    assert config.mt5_execution_enabled is False


def test_observation_is_still_the_default_after_phase_17():
    assert Settings(**BASE).execution_mode == "OBSERVATION"


# -------------------------------------------------------------- the recording
def test_a_shadow_record_carries_the_whole_signal():
    """Section 3, field for field."""
    payload = shadow_signal().as_dict()
    for name in ("shadow_signal_id", "demo_execution_request_id", "symbol", "timestamp",
                 "side", "entry", "stop_loss", "take_profit", "strategy", "model",
                 "confidence", "risk_snapshot_id", "session", "regime", "feature_version",
                 "model_version"):
        assert name in payload


def test_a_shadow_record_reports_zero_orders_sent():
    assert shadow_signal().orders_sent == 0
    assert shadow_signal().as_dict()["orders_sent"] == 0


def test_the_recorder_has_no_way_to_send_anything():
    for name in ("send_order", "send_market_order", "submit", "execute", "order_send",
                 "client", "transmit"):
        assert not hasattr(ShadowRecorder, name)


def test_the_shadow_id_is_derived_from_the_request_id():
    """The pairing is a function, not bookkeeping."""
    from validation.shadow import shadow_signal_id

    request = order()
    signal = shadow_signal(request=request)
    assert signal.shadow_signal_id == shadow_signal_id(request.request_id)
    assert signal.demo_execution_request_id == request.request_id


def test_the_same_request_always_yields_the_same_shadow_id():
    from validation.shadow import shadow_signal_id

    assert shadow_signal_id("abc") == shadow_signal_id("abc")
    assert shadow_signal_id("abc") != shadow_signal_id("abd")


def test_an_unexecuted_signal_says_why():
    from tests.phase16_helpers import armed, chain_for, context

    blocked = chain_for(armed()).evaluate(order(), context(risk_allowed=False))
    signal = shadow_signal(decision=blocked, ctx=context(risk_allowed=False))
    assert signal.executed is False
    assert signal.not_executed_reason == NOT_EXECUTED_BLOCKED
    assert "RISK_ENGINE_BLOCKED" in signal.blocked_reasons


def test_an_approved_but_unsent_signal_says_the_mode_stopped_it():
    signal = shadow_signal()
    assert signal.approved is True
    assert signal.not_executed_reason == NOT_EXECUTED_MODE


def test_a_shadow_record_starts_open():
    assert shadow_signal().status is ShadowStatus.OPEN


def test_the_summary_never_reports_an_order():
    live = recorder()
    shadow_signal(recorder_=live)
    summary = live.summary()
    assert summary["orders_sent"] == 0 and summary["source"] == SHADOW_SOURCE


# ---------------------------------------------------------------- end to end
def test_shadow_mode_sends_nothing_through_the_service(db_session):
    service, fake = service_for(db_session, shadow_settings())
    request = order()
    outcome = service.submit(request, live_context(service, request))

    assert fake.sent == [], "SHADOW must never reach the broker"
    assert not outcome.executed


def test_shadow_mode_still_records_the_signal(db_session):
    service, fake = service_for(db_session, shadow_settings())
    request = order()
    service.submit(request, live_context(service, request))

    row = db_session.query(ShadowSignalRecord).one()
    assert row.demo_execution_request_id == request.request_id
    assert row.orders_sent == 0
    assert row.executed is False


def test_observation_mode_also_sends_nothing(db_session):
    service, fake = service_for(db_session, settings())
    request = order()
    service.submit(request, live_context(service, request))
    assert fake.sent == []


def test_paper_mode_sends_nothing(db_session):
    service, fake = service_for(db_session, settings(demo_execution_mode="PAPER"))
    request = order()
    service.submit(request, live_context(service, request))
    assert fake.sent == []


def test_shadow_mode_records_the_refusal_reason(db_session):
    """Blocked in SHADOW is recorded exactly as it would be in DEMO."""
    service, _ = service_for(db_session, shadow_settings())
    request = order()
    service.submit(request, live_context(service, request))
    result = db_session.query(ExecutionResultRecord).one()
    assert result.status == "BLOCKED"


def test_the_shadow_ledger_is_on_the_status_payload(db_session):
    service, _ = service_for(db_session, shadow_settings())
    request = order()
    service.submit(request, live_context(service, request))
    status = service.status()
    assert status["shadow"]["signals"] == 1
    assert status["shadow"]["orders_sent"] == 0
