"""The Phase 17 mandatory safety tests (sections 1 and 27).

One table, one row per required condition. Everything else in this phase is
measurement; this file is the part that must not regress.

| Condition            | Result |
| SHADOW               | zero broker orders |
| PAPER                | zero broker orders |
| LIVE                 | BLOCK |
| REAL account         | BLOCK |
| kill switch          | BLOCK |
| circuit breaker      | BLOCK |
| reconciliation fail  | BLOCK |
| data stale           | BLOCK |
| model failure        | BLOCK |
| risk failure         | BLOCK |
| unexpected account   | BLOCK |
"""
import ast
import pathlib

import pytest
from pydantic import ValidationError

from config.settings import Settings
from execution.demo.modes import BROKER_MODES, ExecutionMode
from execution.mt5.mock import FakeExecutionModule
from validation.circuit_breaker import BreakerSignals
from tests.phase16_helpers import (
    BASE, DEMO_SERVER, REAL_TRADE_MODE, live_context, order, service_for, settings,
)
from tests.phase17_helpers import shadow_settings

ROOT = pathlib.Path(__file__).resolve().parents[1]


def submit(db_session, config=None, *, module=None, **context_overrides):
    """Run one order through the whole path and report what reached the broker."""
    service, fake = service_for(db_session, config, module=module)
    request = order()
    outcome = service.submit(request, live_context(service, request, **context_overrides))
    return service, fake, outcome


# ------------------------------------------------- SHADOW/PAPER send nothing
def test_shadow_sends_zero_broker_orders(db_session):
    _, fake, outcome = submit(db_session, shadow_settings())
    assert fake.sent == [] and not outcome.executed


def test_paper_sends_zero_broker_orders(db_session):
    _, fake, outcome = submit(db_session, settings(demo_execution_mode="PAPER"))
    assert fake.sent == [] and not outcome.executed


def test_observation_sends_zero_broker_orders(db_session):
    _, fake, outcome = submit(db_session, settings())
    assert fake.sent == [] and not outcome.executed


def test_live_disabled_sends_zero_broker_orders(db_session):
    _, fake, outcome = submit(db_session, settings(demo_execution_mode="LIVE_DISABLED"))
    assert fake.sent == [] and not outcome.executed


def test_only_the_two_demo_modes_can_reach_a_broker():
    assert BROKER_MODES == {ExecutionMode.DEMO_MANUAL_APPROVAL, ExecutionMode.DEMO_AUTOMATED}
    assert ExecutionMode.SHADOW not in BROKER_MODES


# ------------------------------------------------------------------ LIVE
def test_live_trading_cannot_be_enabled():
    with pytest.raises(ValidationError, match="LIVE_TRADING_ENABLED"):
        Settings(**BASE, live_trading_enabled=True)


def test_real_account_execution_cannot_be_enabled():
    with pytest.raises(ValidationError, match="REAL_ACCOUNT_EXECUTION"):
        Settings(**BASE, real_account_execution=True)


def test_no_mode_enables_live_trading():
    for mode in ExecutionMode:
        config = settings(demo_execution_mode=str(mode),
                          demo_automated_execution_enabled=mode is ExecutionMode.DEMO_AUTOMATED)
        assert config.live_trading_enabled is False
        assert config.real_account_execution is False


def test_there_is_no_live_route_and_no_live_adapter():
    from api.main import app

    paths = [route.path.lower() for route in app.routes]
    assert not [path for path in paths
                if any(token in path for token in ("live", "broker", "exness", "metatrader"))]


# ---------------------------------------------------------------- the blocks
def test_a_real_account_blocks(db_session):
    _, fake, outcome = submit(db_session, module=FakeExecutionModule(
        trade_mode=REAL_TRADE_MODE, server=DEMO_SERVER))
    assert not outcome.approved and fake.sent == []
    assert "ACCOUNT_IS_REAL" in outcome.reasons


def test_an_unknown_account_blocks(db_session):
    from observation.demo_account import DemoAccountResult, DemoValidation

    unknown = DemoAccountResult(DemoValidation.UNKNOWN_ACCOUNT,
                                ("ACCOUNT_TRADE_MODE_UNKNOWN",), None, None)
    _, fake, outcome = submit(db_session, account=unknown)
    assert not outcome.approved and fake.sent == []


def test_the_kill_switch_blocks(db_session):
    service, fake = service_for(db_session)
    service.engage_kill_switch("safety test")
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert not outcome.approved and fake.sent == []
    assert "KILL_SWITCH_ENGAGED" in outcome.reasons


def test_the_circuit_breaker_blocks(db_session):
    service, fake = service_for(db_session)
    service.breaker.check(BreakerSignals(daily_drawdown=0.50))
    request = order()
    outcome = service.submit(request, live_context(service, request))
    assert not outcome.executed and fake.sent == []


def test_a_reconciliation_failure_blocks_the_next_order(db_session):
    service, fake = service_for(db_session, module=FakeExecutionModule(
        fill_volume=0.01, retcode=10010, server=DEMO_SERVER))
    first = order(signal_id="signal-001")
    service.submit(first, live_context(service, first))
    assert service.kill_switch.engaged is True

    second = order(signal_id="signal-002")
    outcome = service.submit(second, live_context(service, second))
    assert not outcome.executed
    assert len(fake.sent) == 1, "only the first order reached the broker"


def test_stale_data_blocks(db_session):
    _, fake, outcome = submit(db_session, data_age_seconds=100_000.0)
    assert not outcome.approved and fake.sent == []
    assert "DATA_STALE" in outcome.reasons


def test_bad_data_blocks(db_session):
    failing = {"M5": {"verdict": "FAIL", "reasons": ["BROKEN_OHLC"]}}
    _, fake, outcome = submit(db_session, data_quality=failing, data_quality_ok=None)
    assert not outcome.approved and fake.sent == []


def test_a_model_failure_blocks(db_session):
    _, fake, outcome = submit(db_session, model_failed=True)
    assert not outcome.approved and fake.sent == []
    assert "MODEL_FAILED" in outcome.reasons


def test_a_risk_failure_blocks(db_session):
    _, fake, outcome = submit(db_session, risk_allowed=False)
    assert not outcome.approved and fake.sent == []
    assert "RISK_ENGINE_BLOCKED" in outcome.reasons


def test_an_unexpected_account_trips_the_breaker(db_session):
    service, _ = service_for(db_session, module=FakeExecutionModule(
        trade_mode=REAL_TRADE_MODE, server=DEMO_SERVER))
    event = service.breaker.check(BreakerSignals(account_type="REAL"))
    assert event is not None and service.breaker.open is True


# ------------------------------------------------------- validation is inert
def test_no_validation_module_writes_a_setting():
    """Parse the code: validation reads and reports, it never configures."""
    offenders: list[str] = []
    for path in sorted((ROOT / "validation").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AugAssign):
                targets = [node.target]
            for target in targets:
                if (isinstance(target, ast.Attribute)
                        and isinstance(target.value, ast.Attribute)
                        and target.value.attr == "settings"):
                    offenders.append(f"{path.name}: settings.{target.attr}")
    assert offenders == [], offenders


def test_no_validation_module_holds_an_execution_client():
    forbidden = ("MT5ExecutionClient", "send_market_order", "order_send",
                 "ControlledDemoTradingService")
    offenders: list[str] = []
    for path in sorted((ROOT / "validation").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        hits = [token for token in forbidden if token in text]
        if hits:
            offenders.append(f"{path.name}: {hits}")
    assert offenders == [], offenders


def test_shadow_rows_always_record_zero_orders(db_session):
    from database.models import ShadowSignalRecord

    for index, config in enumerate((shadow_settings(), settings(),
                                    settings(demo_execution_mode="PAPER"))):
        service, fake = service_for(db_session, config)
        request = order(signal_id=f"signal-{index}")
        service.submit(request, live_context(service, request))
        assert fake.sent == []
    rows = db_session.query(ShadowSignalRecord).all()
    assert rows and all(row.orders_sent == 0 for row in rows)


# ------------------------------------------------------------ default posture
def test_the_shipped_defaults_are_unchanged_by_phase_17():
    config = Settings(**BASE)
    assert config.execution_mode == "OBSERVATION"
    assert config.live_trading_enabled is False
    assert config.real_account_execution is False
    assert config.demo_trading_enabled is False
    assert config.mt5_execution_enabled is False
    assert config.execution_kill_switch is True
    assert config.demo_automated_execution_enabled is False
    assert config.demo_automation_approved is False
    assert config.demo_dca_enabled is False


def test_shadow_recording_is_on_and_sends_nothing():
    """The one thing Phase 17 turns on by default. It has no transport."""
    config = Settings(**BASE)
    assert config.shadow_mode_enabled is True
    assert config.circuit_breaker_enabled is True
    assert config.execution_mode == "OBSERVATION"
