"""Account identity, DEMO/REAL validation and login masking."""
import pytest

from execution.mt5.account import (
    ACCOUNT_IS_REAL, AccountValidator, MT5Account, TradeMode, account_from_mt5, parse_trade_mode,
)
from execution.mt5.client import ACCOUNT_BLOCKED
from execution.mt5.connection import ConnectionState, mask_login
from execution.mt5.mock import CONTEST_TRADE_MODE, DEMO_TRADE_MODE, REAL_TRADE_MODE, MockMT5ReadOnlyClient
from tests.phase10_helpers import connected_client, module


def test_demo_account_is_read_and_reported():
    client = connected_client()
    result = client.get_account()
    assert result.ok
    account = result.data
    assert account.trade_mode is TradeMode.DEMO and account.environment == "DEMO"
    assert account.server == "Exness-MT5Trial8" and account.currency == "USD"
    assert account.balance == 10000.0 and account.equity == 10120.5
    assert account.margin == 250.0 and account.free_margin == 9870.5
    assert account.margin_level == 4048.2


def test_a_real_account_is_blocked_and_disconnected():
    client = MockMT5ReadOnlyClient(module=module(trade_mode=REAL_TRADE_MODE))
    report = client.connect()
    assert report.state is ConnectionState.BLOCKED
    assert report.code == ACCOUNT_BLOCKED and ACCOUNT_IS_REAL in report.reasons
    assert not client.is_connected()
    assert client.fake.shutdown_called, "a REAL account must be disconnected immediately"


def test_no_data_is_readable_from_a_real_account():
    client = MockMT5ReadOnlyClient(module=module(trade_mode=REAL_TRADE_MODE))
    client.connect()
    for result in (client.get_tick("EURUSD"), client.get_positions(),
                   client.get_rates("EURUSD", "M15", 10), client.get_orders()):
        assert not result.ok


def test_contest_accounts_are_treated_as_demo():
    client = MockMT5ReadOnlyClient(module=module(trade_mode=CONTEST_TRADE_MODE))
    assert client.connect().state is ConnectionState.CONNECTED
    assert client.get_account().data.environment == "DEMO"


@pytest.mark.parametrize(("raw", "expected"), [
    (DEMO_TRADE_MODE, TradeMode.DEMO), (CONTEST_TRADE_MODE, TradeMode.CONTEST),
    (REAL_TRADE_MODE, TradeMode.REAL), ("DEMO", TradeMode.DEMO), (None, TradeMode.UNKNOWN),
    (99, TradeMode.UNKNOWN), ("nonsense", TradeMode.UNKNOWN),
])
def test_trade_mode_parsing(raw, expected):
    assert parse_trade_mode(raw) is expected


def test_an_unknown_trade_mode_is_refused_rather_than_assumed_demo():
    account = MT5Account(1, "s", "Exness", "USD", 0, 0, 0, 0, 0, TradeMode.UNKNOWN)
    validation = AccountValidator().validate(account)
    assert not validation.allowed and "ACCOUNT_TRADE_MODE_UNKNOWN" in validation.reasons


def test_a_missing_account_is_refused():
    validation = AccountValidator().validate(None)
    assert not validation.allowed and "ACCOUNT_UNAVAILABLE" in validation.reasons


@pytest.mark.parametrize(("login", "expected"), [
    (987654321, "*****4321"), (1234, "****"), (12, "**"), (None, None), ("", None),
])
def test_login_masking(login, expected):
    assert mask_login(login) == expected


def test_the_public_account_payload_carries_no_credential():
    account = connected_client().get_account().data
    payload = account.as_public_dict()
    assert payload["login"] == "*****4321"
    assert str(account.login) not in str(payload)
    assert not any(key in payload for key in ("password", "secret", "token", "credential"))


def test_account_mapping_accepts_both_margin_free_and_free_margin():
    assert account_from_mt5({"margin_free": 5.0}).free_margin == 5.0
    assert account_from_mt5({"free_margin": 7.0}).free_margin == 7.0
