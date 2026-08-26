"""The critical Phase 10 guarantee: MT5 cannot execute a trade.

Checked against the parsed code and the live object graph, not against prose.
"""
import ast
import inspect
import pathlib

import pytest

from data_sources.providers.mt5 import MT5MarketDataProvider
from execution.mt5.client import MT5ReadOnlyClient
from execution.mt5.mock import FakeMT5Module
from execution.mt5.safety import (
    FORBIDDEN_EXECUTION_METHODS,
    MT5SafetyLock,
    ReadOnlyExecutionGuard,
    ReadOnlyModeError,
)
from execution.mt5.service import MT5ReadOnlyService
from tests.phase10_helpers import connected_client

EXECUTION_CALLS = (
    "order_send", "order_check", "order_calc_margin", "order_calc_profit",
    "positions_close", "position_close",
)
PACKAGE = pathlib.Path("execution/mt5")


def test_mt5_cannot_execute_trade():
    """The headline invariant: no execution capability exists on the client."""
    client = connected_client()
    for name in FORBIDDEN_EXECUTION_METHODS:
        assert not hasattr(client, name), name
    assert not hasattr(client, "send_order")
    assert not hasattr(client, "close_position")
    assert not hasattr(client, "modify_order")
    assert not hasattr(client, "open_position")
    assert client.identity()["execution_enabled"] is False
    assert client.identity()["read_only"] is True


def test_the_fake_terminal_itself_offers_no_order_function():
    """Even the test double refuses to model an execution API."""
    module = FakeMT5Module()
    for name in EXECUTION_CALLS:
        assert not hasattr(module, name), name


# Phase 11 introduced exactly one module permitted to transmit an order. Every
# other module in the package must still be free of execution calls.
SANCTIONED_TRANSMITTER = "execution_client.py"


def _execution_calls(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in EXECUTION_CALLS:
            found.add(node.attr)
        if isinstance(node, ast.Name) and node.id in EXECUTION_CALLS:
            found.add(node.id)
    return found


def test_only_the_sanctioned_client_calls_an_execution_function():
    offenders = []
    for path in PACKAGE.glob("*.py"):
        if path.name == SANCTIONED_TRANSMITTER:
            continue
        for call in sorted(_execution_calls(path)):
            offenders.append(f"{path.name}:{call}")
    assert offenders == [], offenders


def test_the_sanctioned_client_is_the_one_that_transmits():
    """Guards the assumption above: if it stops calling order_send, this test tells us."""
    calls = _execution_calls(PACKAGE / SANCTIONED_TRANSMITTER)
    assert "order_send" in calls


def test_the_read_only_client_module_still_calls_nothing():
    assert _execution_calls(PACKAGE / "client.py") == set()


def test_the_provider_adapter_exposes_no_execution_method():
    provider = MT5MarketDataProvider(connected_client(), symbols=("EURUSD",))
    for name in (*FORBIDDEN_EXECUTION_METHODS, *EXECUTION_CALLS):
        assert not hasattr(provider, name), name


def test_the_service_exposes_no_execution_method():
    for name in (*FORBIDDEN_EXECUTION_METHODS, *EXECUTION_CALLS):
        assert not hasattr(MT5ReadOnlyService, name), name


def test_the_shared_interface_guard_refuses_every_execution_call():
    """Provided only for adapters needing a broader interface; it always raises."""
    guard = ReadOnlyExecutionGuard()
    for name in ("send_order", "modify_order", "close_position", "open_position", "place_dca"):
        with pytest.raises(ReadOnlyModeError):
            getattr(guard, name)()


def test_the_read_only_client_does_not_inherit_the_guard():
    """Inheriting it would make hasattr(client, 'send_order') true; it must stay false."""
    assert not issubclass(MT5ReadOnlyClient, ReadOnlyExecutionGuard)


def test_refuse_execution_raises_with_the_operation_named():
    with pytest.raises(ReadOnlyModeError, match="send_order"):
        MT5SafetyLock.refuse_execution("send_order")


def test_no_api_route_can_submit_an_mt5_order():
    from api.main import app

    # Reading orders is allowed; submitting anything is not. Only writes may match.
    forbidden = [route.path for route in app.routes
                 if route.path.startswith("/mt5")
                 and getattr(route, "methods", None)
                 and route.methods - {"GET", "HEAD", "OPTIONS"}
                 and any(token in route.path for token in ("order", "close", "modify", "send"))]
    assert forbidden == [], forbidden
    writable = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
                for route in app.routes
                if getattr(route, "methods", None) and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert {path for path in writable if path.endswith(("/mt5/connect", "/mt5/disconnect"))} == {
        "POST /mt5/connect", "POST /mt5/disconnect"}
    assert not [path for path in writable if "/mt5/" in path
                and not path.endswith(("/mt5/connect", "/mt5/disconnect"))]
