"""The DEMO account guard in front of execution (section 2).

Phase 12 already validates the account for observation. Execution asks a stricter
question — terminal trade permissions must be *known*, not merely not-disabled —
so this file covers the execution posture specifically.
"""
import pytest

from execution.demo.gates import ACCOUNT_NOT_VERIFIED_DEMO, ACCOUNT_UNKNOWN
from execution.mt5.account import MT5Account, TradeMode
from execution.mt5.connection import TerminalInfo
from execution.mt5.mock import FakeExecutionModule
from observation.demo_account import (
    ACCOUNT_IS_REAL, DemoAccountResult, DemoAccountValidator, DemoValidation,
    TERMINAL_API_DISABLED, TERMINAL_PERMISSIONS_UNKNOWN,
)
from tests.phase16_helpers import DEMO_SERVER, armed, chain_for, context, order, service_for


def account(**overrides):
    payload = dict(login=987654321, server=DEMO_SERVER, broker="Exness", currency="USD",
                   balance=10000.0, equity=10000.0, margin=0.0, free_margin=10000.0,
                   margin_level=0.0, trade_mode=TradeMode.DEMO)
    payload.update(overrides)
    return MT5Account(**payload)


def terminal(**overrides):
    payload = dict(available=True, initialized=True, connected=True, trade_allowed=True,
                   tradeapi_disabled=False)
    payload.update(overrides)
    return TerminalInfo(**payload)


# ------------------------------------------------------------- the validator
def test_execution_requires_known_terminal_permissions():
    """Observation tolerates unknown permissions; execution does not."""
    unknown = terminal(trade_allowed=None, tradeapi_disabled=None)
    observing = DemoAccountValidator(armed()).validate(account(), terminal=unknown, connected=True)
    executing = DemoAccountValidator(armed(), require_permissions=True).validate(
        account(), terminal=unknown, connected=True)

    assert observing.valid
    assert not executing.valid
    assert TERMINAL_PERMISSIONS_UNKNOWN in executing.reasons


def test_a_barred_trading_api_is_an_invalid_account():
    result = DemoAccountValidator(armed(), require_permissions=True).validate(
        account(), terminal=terminal(tradeapi_disabled=True), connected=True)
    assert result.status is DemoValidation.INVALID_ACCOUNT
    assert TERMINAL_API_DISABLED in result.reasons


def test_a_verified_demo_account_passes():
    result = DemoAccountValidator(armed(), require_permissions=True).validate(
        account(), terminal=terminal(), connected=True)
    assert result.status is DemoValidation.VALID_DEMO


def test_a_real_account_outranks_every_other_verdict():
    """Even disconnected, a REAL account reports as REAL rather than as unreachable."""
    result = DemoAccountValidator(armed(), require_permissions=True).validate(
        account(trade_mode=TradeMode.REAL), terminal=terminal(connected=False), connected=False)
    assert result.status is DemoValidation.INVALID_ACCOUNT
    assert result.reasons == (ACCOUNT_IS_REAL,)


def test_an_unreachable_terminal_is_a_connection_error():
    result = DemoAccountValidator(armed(), require_permissions=True).validate(
        None, terminal=terminal(available=False), connected=False)
    assert result.status is DemoValidation.CONNECTION_ERROR


# ------------------------------------------------------------------ the gate
def test_the_gate_treats_a_connection_error_as_a_block():
    unreachable = DemoAccountResult(DemoValidation.CONNECTION_ERROR, ("NOT_CONNECTED",), None, None)
    decision = chain_for().evaluate(order(), context(account=unreachable))
    assert not decision.approved
    assert ACCOUNT_UNKNOWN in decision.reasons


def test_the_gate_names_itself_when_it_blocks():
    decision = chain_for().evaluate(order(), context(account=None))
    assert "DemoAccountValidator" in decision.blocked_by
    assert ACCOUNT_NOT_VERIFIED_DEMO in decision.reasons


def test_the_account_gate_is_first_in_the_chain():
    """Section 5 fixes the order; the dashboard renders it verbatim."""
    assert chain_for().gate_names()[0] == "DemoAccountValidator"


# ---------------------------------------------------------------- end to end
def test_a_disconnected_terminal_blocks_the_service(db_session):
    service, fake = service_for(db_session)
    service.read_client.disconnect()

    request = order()
    outcome = service.submit(request, service.build_context(
        request, data_quality_ok=True, risk_allowed=True, strategy_status="CHAMPION",
        strategy_decision="EXECUTABLE_SIMULATION", model_confidence=0.72, session="LONDON"))
    assert not outcome.approved
    assert fake.sent == []


def test_a_verified_demo_account_reaches_the_broker(db_session):
    from tests.phase16_helpers import live_context

    service, fake = service_for(db_session, module=FakeExecutionModule(server=DEMO_SERVER))
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert outcome.executed and len(fake.sent) == 1
