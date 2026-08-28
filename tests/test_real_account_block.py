"""A REAL account may never execute (sections 2 and 33).

The refusal is checked in four independent places, and each one is tested here:
configuration, the account gate, the Phase 11 guard, and the execution client
immediately before transmission.
"""
import pytest
from pydantic import ValidationError

from config.settings import Settings
from database.models import DashboardAlertRecord, ExecutionResultRecord
from execution.demo.gates import ACCOUNT_IS_REAL, ACCOUNT_UNKNOWN
from execution.mt5.account import MT5Account, TradeMode
from execution.mt5.mock import FakeExecutionModule
from observation.demo_account import DemoAccountResult, DemoValidation
from tests.phase16_helpers import (
    BASE, DEMO_SERVER, REAL_TRADE_MODE, armed, chain_for, context, demo_account, live_context,
    order, service_for,
)


def real_account(**overrides):
    account = MT5Account(login=1, server="Exness-Real12", broker="Exness", currency="USD",
                         balance=1000.0, equity=1000.0, margin=0.0, free_margin=1000.0,
                         margin_level=0.0, trade_mode=TradeMode.REAL)
    return DemoAccountResult(DemoValidation.INVALID_ACCOUNT, (ACCOUNT_IS_REAL,), account, None)


# ------------------------------------------------------------- configuration
def test_real_account_execution_cannot_be_enabled():
    with pytest.raises(ValidationError, match="REAL_ACCOUNT_EXECUTION"):
        Settings(**BASE, real_account_execution=True)


def test_the_shipped_default_refuses_real_account_execution():
    assert Settings(**BASE).real_account_execution is False


def test_live_trading_remains_impossible_in_every_mode():
    for mode in ("OBSERVATION", "PAPER", "DEMO_MANUAL_APPROVAL", "LIVE_DISABLED"):
        config = Settings(**BASE, demo_execution_mode=mode,
                          demo_trading_enabled=mode.startswith("DEMO"))
        assert config.live_trading_enabled is False
        assert config.real_account_execution is False


# ------------------------------------------------------------------ the gate
def test_a_real_account_blocks_the_chain():
    decision = chain_for().evaluate(order(), context(account=real_account()))
    assert not decision.approved
    assert ACCOUNT_IS_REAL in decision.reasons
    assert "DemoAccountValidator" in decision.blocked_by


def test_an_unknown_account_blocks_the_chain():
    unknown = DemoAccountResult(DemoValidation.UNKNOWN_ACCOUNT,
                                ("ACCOUNT_TRADE_MODE_UNKNOWN",), None, None)
    decision = chain_for().evaluate(order(), context(account=unknown))
    assert not decision.approved
    assert ACCOUNT_UNKNOWN in decision.reasons


def test_a_missing_account_blocks_the_chain():
    decision = chain_for().evaluate(order(), context(account=None))
    assert not decision.approved
    assert "ACCOUNT_NOT_VERIFIED_DEMO" in decision.reasons


def test_a_demo_account_on_a_non_demo_server_blocks():
    account = demo_account()
    from dataclasses import replace

    on_real_server = replace(account, account=replace(account.account, server="Exness-Live7"))
    decision = chain_for().evaluate(order(), context(account=on_real_server))
    assert not decision.approved
    assert "SERVER_NOT_DEMO" in decision.reasons


# ---------------------------------------------------------------- end to end
def test_a_real_account_is_refused_by_the_whole_service(db_session):
    service, _ = service_for(db_session, module=FakeExecutionModule(
        trade_mode=REAL_TRADE_MODE, server=DEMO_SERVER))
    request = order()
    outcome = service.submit(request, live_context(service, request))

    assert not outcome.approved and not outcome.executed
    assert ACCOUNT_IS_REAL in outcome.reasons


def test_a_real_account_refusal_is_persisted_and_alerted(db_session):
    service, fake = service_for(db_session, module=FakeExecutionModule(
        trade_mode=REAL_TRADE_MODE, server=DEMO_SERVER))
    request = order()
    service.submit(request, live_context(service, request))

    assert fake.sent == [], "nothing may be transmitted on a REAL account"
    result = db_session.query(ExecutionResultRecord).one()
    assert result.status == "BLOCKED"
    alerts = db_session.query(DashboardAlertRecord).all()
    critical = [row for row in alerts if row.severity == "CRITICAL"]
    assert critical, "a REAL account is the most serious alert this system raises"
    assert any(row.alert_type == "REAL_ACCOUNT_BLOCKED" for row in alerts)


def test_the_execution_client_refuses_a_real_account_even_with_an_approval(db_session):
    """The last line of defence: the account is re-read before transmission."""
    service, fake = service_for(db_session)
    request = order()
    decision = service.chain.evaluate(request, live_context(service, request))
    assert decision.approved

    fake.trade_mode = REAL_TRADE_MODE
    result = service.client.send_market_order(request.to_order_request(), decision.guard)
    assert result.blocked and result.error_code == "ACCOUNT_IS_REAL"
    assert fake.sent == []
