"""The Phase 11 critical safety matrix (§17).

Each case asserts both that the order is refused AND that nothing reached the
terminal — a refusal that still transmitted would be worthless.
"""
import pytest
from pydantic import ValidationError

from config.settings import Settings, get_settings
from execution.mt5.execution_client import ExecutionTransportError, MT5ExecutionClient
from execution.mt5.execution_guard import GuardDecision
from execution.mt5.mock import FakeExecutionModule
from execution.mt5.order_result import RejectionReason
from tests.phase11_helpers import BASE, DEMO_SERVER, REAL_TRADE_MODE, armed, order, service_for, settings


def run(db_session, config=None, *, module=None):
    service, fake = service_for(db_session, config, module=module)
    outcome = service.execute(order())
    return outcome, fake


# ------------------------------------------------------------------- 17. BLOCK
def test_real_account_blocks_and_transmits_nothing(db_session):
    outcome, fake = run(db_session, module=FakeExecutionModule(
        trade_mode=REAL_TRADE_MODE, server=DEMO_SERVER))
    assert not outcome.executed
    assert RejectionReason.ACCOUNT_IS_REAL in outcome.result.reasons
    assert fake.sent == [], "nothing may be transmitted for a REAL account"


def test_live_environment_blocks(db_session):
    config = armed()
    object.__setattr__(config, "live_trading_enabled", True)
    outcome, fake = run(db_session, config)
    assert not outcome.executed
    assert RejectionReason.LIVE_TRADING_ENABLED in outcome.result.reasons
    assert fake.sent == []


def test_live_trading_enabled_cannot_even_be_configured():
    with pytest.raises(ValidationError, match="LIVE_TRADING_ENABLED"):
        Settings(**BASE, live_trading_enabled=True)


def test_kill_switch_blocks(db_session):
    service, fake = service_for(db_session)
    service.engage_kill_switch("safety test")
    outcome = service.execute(order())
    assert not outcome.executed
    assert RejectionReason.KILL_SWITCH_ENGAGED in outcome.result.reasons
    assert fake.sent == []


def test_risk_blocked_blocks(db_session):
    service, fake = service_for(db_session)
    context = service.build_context(order())
    from dataclasses import replace

    outcome = service.execute(order(), replace(context, risk_allowed=False))
    assert not outcome.executed
    assert RejectionReason.RISK_BLOCKED in outcome.result.reasons
    assert fake.sent == []


def test_extreme_spread_blocks(db_session):
    service, fake = service_for(db_session)
    from dataclasses import replace

    context = replace(service.build_context(order()), quote={"bid": 1.10, "ask": 1.12})
    outcome = service.execute(order(), context)
    assert not outcome.executed
    assert RejectionReason.SPREAD_TOO_WIDE in outcome.result.reasons
    assert fake.sent == []


def test_invalid_volume_blocks(db_session):
    service, fake = service_for(db_session)
    outcome = service.execute(order(volume=99.0))
    assert not outcome.executed
    assert RejectionReason.VOLUME_ABOVE_LIMIT in outcome.result.reasons
    assert fake.sent == []


def test_invalid_symbol_blocks(db_session):
    service, fake = service_for(db_session)
    outcome = service.execute(order(symbol="ZZZZZZ"))
    assert not outcome.executed
    assert RejectionReason.INVALID_SYMBOL in outcome.result.reasons
    assert fake.sent == []


def test_dca_limit_exceeded_blocks(db_session):
    from dataclasses import replace

    from execution.mt5.order_request import ExecutionIntent

    service, fake = service_for(db_session)
    context = replace(service.build_context(order()), dca_entries=5,
                      strategy_status="EXECUTABLE_SIMULATION")
    outcome = service.execute(order(intent=ExecutionIntent.DCA), context)
    assert not outcome.executed
    assert RejectionReason.DCA_LIMIT in outcome.result.reasons
    assert fake.sent == []


def test_demo_execution_disabled_blocks(db_session):
    outcome, fake = run(db_session, settings())            # every gate closed
    assert not outcome.executed
    assert RejectionReason.DEMO_TRADING_DISABLED in outcome.result.reasons
    assert RejectionReason.MT5_EXECUTION_DISABLED in outcome.result.reasons
    assert fake.sent == []


# ------------------------------------------------------------------- 17. ALLOW
def test_only_a_fully_valid_demo_configuration_executes(db_session):
    outcome, fake = run(db_session)
    assert outcome.decision.approved and outcome.executed
    assert outcome.result.broker_ticket is not None
    assert len(fake.sent) == 1
    assert fake.sent[0]["symbol"] == "EURUSDm" and fake.sent[0]["volume"] == 0.01


# ------------------------------------------------------- guard cannot be bypassed
def test_the_client_refuses_to_transmit_without_a_guard_approval(db_session):
    service, fake = service_for(db_session)
    with pytest.raises(ExecutionTransportError, match="approval is required"):
        service.client.send_market_order(order(), None)
    assert fake.sent == []


def test_the_client_refuses_a_refused_approval(db_session):
    service, fake = service_for(db_session)
    request = order()
    refused = GuardDecision(False, request.request_id, ("RISK_BLOCKED",))
    with pytest.raises(ExecutionTransportError, match="guard refused"):
        service.client.send_market_order(request, refused)
    assert fake.sent == []


def test_the_client_refuses_an_approval_for_a_different_request(db_session):
    """An approval cannot be replayed against another order."""
    service, fake = service_for(db_session)
    approved_elsewhere = GuardDecision(True, "some-other-request-id")
    with pytest.raises(ExecutionTransportError, match="does not match"):
        service.client.send_market_order(order(), approved_elsewhere)
    assert fake.sent == []


def test_the_client_re_checks_the_account_immediately_before_transmitting(db_session):
    """Even with a valid approval, a REAL account stops transmission at the last step."""
    service, fake = service_for(db_session)
    request = order()
    approval = GuardDecision(True, request.request_id)
    fake.trade_mode = REAL_TRADE_MODE
    result = service.client.send_market_order(request, approval)
    assert not result.accepted
    assert RejectionReason.ACCOUNT_IS_REAL in result.reasons
    assert fake.sent == []


# ------------------------------------------------------------ default posture
def test_the_shipped_defaults_permit_no_execution():
    config = get_settings()
    assert config.execution_kill_switch is True
    assert config.demo_trading_enabled is False
    assert config.mt5_execution_enabled is False
    assert config.execution_allowed_by_config is False


def test_no_automated_trading_is_enabled_anywhere(db_session):
    service, _ = service_for(db_session)
    status = service.status()
    assert status["automated_trading"] is False
    assert status["strategy_auto_execution"] is False
    assert status["execution_mode"] == "MANUAL_DEMO_TEST"
