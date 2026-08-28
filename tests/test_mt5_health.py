"""MT5 connection and terminal health validation (Phase 12 section 2)."""
import pytest

from execution.mt5.connection import MT5Connection, TerminalInfo
from execution.mt5.health import HealthState
from observation.health import ComponentHealth, SystemHealthMonitor
from tests.phase12_helpers import DEMO_SERVER, NOW, client, module


def test_terminal_reports_availability_initialisation_and_connection():
    connected = client()
    terminal = connected.connection.terminal_info()
    assert terminal.available and terminal.initialized and terminal.connected


def test_terminal_reports_build_and_identity():
    terminal = client().connection.terminal_info()
    assert terminal.build == 4620
    assert terminal.name and terminal.company and terminal.path


def test_terminal_reports_permissions():
    terminal = client().connection.terminal_info()
    assert terminal.trade_allowed is True
    assert terminal.tradeapi_disabled is False
    assert terminal.permissions_known


def test_a_terminal_with_the_api_disabled_is_reported():
    terminal = client(tradeapi_disabled=True).connection.terminal_info()
    assert terminal.tradeapi_disabled is True


def test_an_uninitialised_terminal_is_not_connected():
    connection = MT5Connection(module=module(initialize_result=False))
    report = connection.connect()
    assert report.code == "MT5_TERMINAL_NOT_AVAILABLE"
    assert not connection.is_connected()


def test_a_missing_package_is_reported_not_raised():
    connection = MT5Connection(module=None)
    report = connection.connect()
    assert report.code == "MT5_PACKAGE_NOT_INSTALLED"
    assert not connection.is_connected()


def test_account_login_status_and_server_are_available():
    connected = client()
    account = connected.get_account()
    assert account.ok
    assert account.data.server == DEMO_SERVER
    assert account.data.masked_login and account.data.masked_login.startswith("*")


def test_symbol_and_market_availability_are_reported():
    connected = client()
    assert connected.get_symbols().ok
    assert connected.resolve_symbol("EURUSD").ok
    assert connected.get_tick("EURUSD").ok


def test_health_check_reports_online_for_a_healthy_terminal():
    connected = client()
    connected.get_tick("EURUSD")
    report = connected.health_check(database_online=True)
    assert report.state in {HealthState.ONLINE, HealthState.DEGRADED}


def test_terminal_info_never_exposes_a_credential():
    payload = client().connection.terminal_info().as_dict()
    assert not any(token in str(payload).lower()
                   for token in ("password", "secret", "token", "credential"))


def test_system_health_maps_component_states():
    monitor = SystemHealthMonitor()
    health = monitor.build({"api": "ONLINE", "database": True, "mt5": "OFFLINE",
                            "strategy": "DEGRADED"})
    assert health.components["api"].state is ComponentHealth.HEALTHY
    assert health.components["database"].state is ComponentHealth.HEALTHY
    assert health.components["mt5"].state is ComponentHealth.FAILED
    assert health.components["strategy"].state is ComponentHealth.DEGRADED
    # Anything not reported stays UNKNOWN rather than being assumed healthy.
    assert health.components["nn"].state is ComponentHealth.UNKNOWN
    assert health.state is ComponentHealth.FAILED


def test_unknown_is_more_severe_than_degraded():
    """A component we cannot see is more dangerous than one we know is impaired."""
    monitor = SystemHealthMonitor()
    health = monitor.build({name: "DEGRADED" for name in monitor.components} | {"nn": None})
    assert health.state is ComponentHealth.UNKNOWN
