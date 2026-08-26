"""Safety lock and read-only enforcement."""
import pytest
from pydantic import ValidationError

from config.settings import Settings, get_settings
from execution.mt5.connection import ConnectionState, MT5Connection
from execution.mt5.safety import MT5SafetyLock, ReadOnlyModeError, SafetyBlock
from tests.phase10_helpers import connected_client, module

BASE = dict(database_url="sqlite://", tradingview_webhook_secret="a-secure-test-secret-of-24-chars")


@pytest.mark.parametrize(("field", "value"), [
    ("live_trading_enabled", True),
    ("demo_trading_enabled", True),
    ("trading_environment", "REAL"),
    ("read_only_mode", False),
    ("mt5_read_only", False),
    ("mt5_execution_enabled", True),
])
def test_settings_refuse_every_unsafe_phase_10_flag(field, value):
    with pytest.raises(ValidationError):
        Settings(**BASE, **{field: value})


def test_default_settings_are_the_required_phase_10_posture():
    settings = get_settings()
    assert settings.environment == "DEMO"
    assert settings.read_only_mode and settings.mt5_read_only
    assert not settings.mt5_execution_enabled
    assert not settings.live_trading_enabled and not settings.demo_trading_enabled


def test_safety_lock_allows_a_correctly_configured_read_only_demo():
    lock = MT5SafetyLock(get_settings())
    assert lock.evaluate_connection().allowed
    assert lock.evaluate_data_access().allowed


class Drifted:
    """A Settings-like object that drifted in memory after construction."""

    trading_environment = "DEMO"
    live_trading_enabled = False
    demo_trading_enabled = False
    read_only_mode = True
    mt5_read_only = True
    mt5_execution_enabled = True
    mt5_server = "Exness-MT5Trial8"
    mt5_login = 987654321
    mt5_password = None
    mt5_terminal_path = None
    mt5_timeout_ms = 30000

    def mt5_credentials_present(self) -> bool:
        return False


def test_safety_lock_blocks_connection_and_data_when_configuration_drifts():
    lock = MT5SafetyLock(Drifted())
    connection = lock.evaluate_connection()
    data = lock.evaluate_data_access()
    assert connection.block is SafetyBlock.BLOCK_CONNECTION
    assert data.block is SafetyBlock.BLOCK_DATA_ACCESS
    assert "MT5_EXECUTION_ENABLED" in connection.reasons
    with pytest.raises(ReadOnlyModeError):
        lock.assert_connection_allowed()
    with pytest.raises(ReadOnlyModeError):
        lock.assert_data_access_allowed()


def test_a_blocked_lock_stops_the_connection_before_the_terminal_is_touched():
    fake = module()
    connection = MT5Connection(Drifted(), module=fake, safety=MT5SafetyLock(Drifted()))
    report = connection.connect()
    assert report.state is ConnectionState.BLOCKED
    assert report.code == "BLOCK_CONNECTION"
    assert not fake.initialized, "initialize must not be called when blocked"


def test_a_blocked_lock_stops_every_read():
    client = connected_client()
    client.safety = MT5SafetyLock(Drifted())
    for result in (client.get_symbols(refresh=True), client.get_positions(), client.get_orders(),
                   client.get_history()):
        assert not result.ok
        assert result.code == "BLOCK_DATA_ACCESS"


def test_the_lock_never_repairs_configuration_by_itself():
    drifted = Drifted()
    MT5SafetyLock(drifted).evaluate_connection()
    assert drifted.mt5_execution_enabled is True, "the lock must block, never silently fix"
