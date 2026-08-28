"""DemoAccountValidator: four explicit outcomes, only one of which permits anything."""
import pytest

from execution.mt5.account import MT5Account, TradeMode
from execution.mt5.connection import TerminalInfo
from observation.demo_account import (
    ACCOUNT_IS_REAL,
    ACCOUNT_TRADE_MODE_UNKNOWN,
    DemoAccountValidator,
    DemoValidation,
    SERVER_NOT_DEMO,
    SERVER_UNVERIFIED,
    TERMINAL_API_DISABLED,
    TERMINAL_UNAVAILABLE,
)
from tests.phase12_helpers import DEMO_SERVER, REAL_TRADE_MODE, client, module


def account(**overrides):
    base = dict(login=987654321, server=DEMO_SERVER, broker="Exness", currency="USD",
                balance=10000.0, equity=10000.0, margin=0.0, free_margin=10000.0,
                margin_level=0.0, trade_mode=TradeMode.DEMO)
    base.update(overrides)
    return MT5Account(**base)


def terminal(**overrides):
    base = dict(available=True, initialized=True, connected=True, build=4620,
                trade_allowed=True, tradeapi_disabled=False)
    base.update(overrides)
    return TerminalInfo(**base)


def test_a_verified_demo_account_is_valid():
    result = DemoAccountValidator().validate(account(), terminal=terminal(), connected=True)
    assert result.status is DemoValidation.VALID_DEMO and result.valid


def test_a_contest_account_is_accepted_as_demo():
    result = DemoAccountValidator().validate(account(trade_mode=TradeMode.CONTEST),
                                             terminal=terminal(), connected=True)
    assert result.status is DemoValidation.VALID_DEMO


def test_a_real_account_is_invalid():
    result = DemoAccountValidator().validate(account(trade_mode=TradeMode.REAL),
                                             terminal=terminal(), connected=True)
    assert result.status is DemoValidation.INVALID_ACCOUNT
    assert ACCOUNT_IS_REAL in result.reasons and result.blocked


def test_a_real_account_outranks_a_connection_problem():
    """A REAL account must name itself even when the terminal has disconnected."""
    result = DemoAccountValidator().validate(account(trade_mode=TradeMode.REAL),
                                             terminal=terminal(connected=False), connected=False)
    assert result.status is DemoValidation.INVALID_ACCOUNT
    assert ACCOUNT_IS_REAL in result.reasons


def test_an_unknown_trade_mode_is_unknown_not_demo():
    result = DemoAccountValidator().validate(account(trade_mode=TradeMode.UNKNOWN),
                                             terminal=terminal(), connected=True)
    assert result.status is DemoValidation.UNKNOWN_ACCOUNT
    assert ACCOUNT_TRADE_MODE_UNKNOWN in result.reasons


@pytest.mark.parametrize("server", ["Exness-Real9", "LiveServer-1"])
def test_a_non_demo_server_is_invalid(server):
    result = DemoAccountValidator().validate(account(server=server), terminal=terminal(),
                                             connected=True)
    assert result.status is DemoValidation.INVALID_ACCOUNT
    assert SERVER_NOT_DEMO in result.reasons


def test_an_unverifiable_server_is_unknown():
    result = DemoAccountValidator().validate(account(server=""), terminal=terminal(),
                                             connected=True)
    assert result.status is DemoValidation.UNKNOWN_ACCOUNT
    assert SERVER_UNVERIFIED in result.reasons


def test_an_unverifiable_broker_is_unknown():
    result = DemoAccountValidator().validate(account(broker=""), terminal=terminal(),
                                             connected=True)
    assert result.status is DemoValidation.UNKNOWN_ACCOUNT


def test_a_terminal_with_the_api_disabled_is_invalid():
    result = DemoAccountValidator().validate(account(), terminal=terminal(tradeapi_disabled=True),
                                             connected=True)
    assert result.status is DemoValidation.INVALID_ACCOUNT
    assert TERMINAL_API_DISABLED in result.reasons


def test_an_unavailable_terminal_is_a_connection_error():
    result = DemoAccountValidator().validate(None, terminal=terminal(available=False))
    assert result.status is DemoValidation.CONNECTION_ERROR
    assert TERMINAL_UNAVAILABLE in result.reasons


def test_a_disconnected_terminal_is_a_connection_error():
    result = DemoAccountValidator().validate(account(), terminal=terminal(connected=False),
                                             connected=False)
    assert result.status is DemoValidation.CONNECTION_ERROR


def test_a_missing_account_is_a_connection_error():
    result = DemoAccountValidator().validate(None, terminal=terminal(), connected=True)
    assert result.status is DemoValidation.CONNECTION_ERROR


def test_unknown_permissions_only_block_when_required():
    stripped = terminal(trade_allowed=None, tradeapi_disabled=None)
    assert DemoAccountValidator().validate(account(), terminal=stripped,
                                           connected=True).status is DemoValidation.VALID_DEMO
    strict = DemoAccountValidator(require_permissions=True)
    assert strict.validate(account(), terminal=stripped,
                           connected=True).status is DemoValidation.UNKNOWN_ACCOUNT


def test_validating_a_live_client_returns_valid_demo():
    result = DemoAccountValidator().validate_client(client())
    assert result.status is DemoValidation.VALID_DEMO


def test_validating_a_real_client_returns_invalid_account():
    result = DemoAccountValidator().validate_client(client(trade_mode=REAL_TRADE_MODE))
    assert result.status is DemoValidation.INVALID_ACCOUNT
    assert ACCOUNT_IS_REAL in result.reasons


def test_the_public_payload_exposes_only_safe_account_information():
    payload = DemoAccountValidator().validate_client(client()).as_dict()
    detail = payload["account"]
    assert detail["login"].startswith("*") and "987654321" not in str(payload)
    assert not any(token in str(payload).lower()
                   for token in ("password", "secret", "credential"))
    assert detail["broker"] and detail["server"] and detail["account_type"] == "DEMO"
