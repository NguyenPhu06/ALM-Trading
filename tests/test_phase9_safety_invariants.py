"""System-level safety invariants for Phase 9.

The Phase 9 baseline asserted `client.post('/live/order').status_code == 404`,
which any undefined route satisfies and therefore proved nothing. These tests
check the actual surface instead.
"""
import inspect

import pytest

from api.main import app
from config.settings import get_settings
from orchestration import OrchestrationCycle
from orchestration.runner import OrchestrationRunner
from paper import (
    EnvironmentSafetyLock,
    LiveExecutionBlocked,
    PaperExecutionEngine,
    PaperRiskEngine,
    TradingEnvironment,
)
from paper.service import bound_repository
from database.repositories import PaperTradingRepository
from tests.phase8_helpers import QUOTE, request
from tests.phase9_helpers import NOW, StubInference, seed_market

FORBIDDEN_ROUTE_TOKENS = ("live", "demo", "broker", "mt5", "exness", "metatrader")


# ------------------------------------------------------------ 40. no live route
def test_no_route_exposes_live_demo_or_broker_execution():
    paths = [route.path.lower() for route in app.routes]
    offenders = [path for path in paths
                 if any(token in path for token in FORBIDDEN_ROUTE_TOKENS)]
    assert offenders == [], offenders


def test_no_route_accepts_an_order_submission():
    """The only write endpoints are paper service control and a paper close."""
    writable = sorted(
        f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
        for route in app.routes
        if getattr(route, "methods", None) and route.methods - {"GET", "HEAD", "OPTIONS"}
    )
    assert writable == [
        "POST /paper/close-position/{position_id}",
        "POST /paper/pause",
        "POST /paper/start",
        "POST /paper/stop",
        "POST /webhooks/tradingview",
    ]


def test_live_environment_is_refused_by_the_execution_engine():
    with pytest.raises(LiveExecutionBlocked):
        PaperExecutionEngine().execute(request(), quote=QUOTE, environment=TradingEnvironment.LIVE)
    with pytest.raises(LiveExecutionBlocked):
        EnvironmentSafetyLock(live_trading_enabled=True).assert_allowed(TradingEnvironment.PAPER)


def test_settings_refuse_to_enable_live_or_demo_trading():
    settings = get_settings()
    assert not settings.live_trading_enabled and not settings.demo_trading_enabled


def test_the_orchestration_cycle_only_calls_the_paper_service():
    """Inspect the parsed code, not the prose, for any non-paper execution route."""
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(OrchestrationCycle)))
    identifiers = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    identifiers |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    offenders = [name for name in identifiers
                 if any(token in name.lower() for token in FORBIDDEN_ROUTE_TOKENS)]
    assert offenders == [], offenders
    assert "self.paper.enter(" in inspect.getsource(OrchestrationCycle)


def test_the_orchestration_loop_is_opt_in(db_session):
    """Starting the API must not start trading activity on its own."""
    runner = OrchestrationRunner(lambda: db_session, None)
    assert runner.enabled is False
    assert runner.start_background() is None
    assert runner.run_forever(max_ticks=1) == 0


# ------------------------------------------------------- 41. no future data
def test_the_loop_never_consumes_a_candle_stamped_after_the_tick(db_session):
    from paper import PaperTradingService

    service = PaperTradingService()
    service.start()
    seed_market(db_session)
    result = OrchestrationCycle(db_session, paper_service=service, now=NOW,
                                inference=StubInference()).run("EURUSD")
    assert result.source_timestamp <= NOW
    order = result.executed.order
    assert order.timestamp >= result.source_timestamp


def test_an_order_whose_source_is_newer_than_its_execution_is_refused():
    from datetime import timedelta

    from paper.models import Direction, OrderType, PaperOrderRequest

    future = PaperOrderRequest("EURUSD", Direction.LONG, OrderType.MARKET, 1., NOW,
                               source_timestamp=NOW + timedelta(minutes=1))
    result = PaperExecutionEngine().execute(future, quote=QUOTE)
    assert not result.accepted and result.rejection_reason == "FUTURE_DATA_REJECTED"


# ------------------------------------------------------------ 42. kill switch
def test_kill_switch_blocks_entries_and_dca_but_not_getting_flat():
    engine = PaperRiskEngine()
    engine.kill_switch.activate()
    assert not engine.evaluate(new_entry=True).allowed
    assert not engine.evaluate(new_entry=False, increases_exposure=True).allowed
    assert engine.evaluate(new_entry=False).allowed


def test_kill_switch_stops_the_orchestration_loop_from_opening_a_position(db_session):
    from paper import PaperTradingService

    service = PaperTradingService()
    service.start()
    service.risk.kill_switch.activate()
    seed_market(db_session)
    with bound_repository(service, PaperTradingRepository(db_session)):
        result = OrchestrationCycle(db_session, paper_service=service, now=NOW,
                                    inference=StubInference()).run("EURUSD")
    assert result.executed.rejection_reason == "GLOBAL_KILL_SWITCH"
    assert not service.positions


# ------------------------------------------------------------------- 43. DCA
@pytest.mark.parametrize(("override", "expected"), [
    ({"data_quality": "INVALID"}, "DATA_QUALITY_INVALID"),
    ({"provider_status": "OFFLINE"}, "PROVIDER_UNAVAILABLE"),
    ({"provider_status": "DEGRADED"}, "PROVIDER_UNAVAILABLE"),
    ({"prediction": None}, "MODEL_FAILURE"),
])
def test_dca_cannot_bypass_a_gate_that_entry_enforces(override, expected):
    from paper.models import OrderType
    from tests.phase8_helpers import PRED, RISK_OK, running_service

    service = running_service()
    entry = service.enter(request(), quote=QUOTE, setup_status="EXECUTABLE_SIMULATION",
                          risk_decision=RISK_OK, data_quality="VALID",
                          provider_status="ONLINE", prediction=PRED)
    position_id = entry.order.position_id
    arguments = {"quote": QUOTE, "market_regime": "TRENDING", "structure_state": "VALID",
                 "risk_state": "ALLOWED", "data_quality": "VALID",
                 "provider_status": "ONLINE", "prediction": PRED}
    arguments.update(override)
    result = service.dca(position_id, request(OrderType.DCA, position_id=position_id), **arguments)
    assert not result.accepted and result.rejection_reason == expected
    assert service.positions[position_id].dca_entries == 0


def test_dca_requires_its_safety_inputs_to_be_supplied_explicitly():
    """They are required keyword arguments, so a caller cannot silently omit them."""
    signature = inspect.signature(
        __import__("paper.service", fromlist=["PaperTradingService"]).PaperTradingService.dca)
    for name in ("data_quality", "provider_status", "prediction"):
        assert signature.parameters[name].default is inspect.Parameter.empty, name
