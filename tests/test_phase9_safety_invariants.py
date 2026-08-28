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

# Phase 10 sanctions a READ-ONLY MT5 data surface, so "mt5" is no longer forbidden
# outright; test_mt5_routes_are_read_only below constrains it instead.
# "demo" is no longer forbidden outright: Phase 11 sanctions ONE manual DEMO
# execution route, pinned by name below. "live" and "broker" remain forbidden.
FORBIDDEN_ROUTE_TOKENS = ("live", "broker", "exness", "metatrader")
# Phase 16 adds a gated DEMO proposal route and its dashboard panel. Both are
# DEMO-only by construction; "live" and "broker" remain forbidden outright.
SANCTIONED_DEMO_ROUTES = {"/execution/demo/test", "/execution/demo/propose",
                          "/dashboard/demo-execution"}
READ_ONLY_MT5_WRITES = {"POST /mt5/connect", "POST /mt5/disconnect"}
EXECUTION_WRITES = {"POST /execution/demo/test", "POST /execution/kill-switch/engage",
                    "POST /execution/kill-switch/release",
                    # Phase 16: propose one gated DEMO order, and approve or reject
                    # it. None of the three can reach a broker on its own; the gate
                    # chain and ExecutionGuard still decide per order.
                    "POST /execution/demo/propose",
                    "POST /execution/proposals/{proposal_id}/approve",
                    "POST /execution/proposals/{proposal_id}/reject"}
# Phase 12 adds one write: running an observation cycle. It sends no order.
OBSERVATION_WRITES = {"POST /observation/cycle"}
# Phase 13 adds two human-gated writes. Neither trains a model and neither trades:
# a retraining request is a record, and approval is the promotion gate.
AI_WRITES = {"POST /ai/retraining/request", "POST /ai/models/{model_id}/approve"}


# ------------------------------------------------------------ 40. no live route
def test_no_route_exposes_live_or_broker_execution():
    paths = [route.path.lower() for route in app.routes]
    offenders = [path for path in paths
                 if any(token in path for token in FORBIDDEN_ROUTE_TOKENS)]
    assert offenders == [], offenders


def test_only_the_sanctioned_demo_route_mentions_demo():
    paths = {route.path for route in app.routes if "demo" in route.path.lower()}
    assert paths == SANCTIONED_DEMO_ROUTES, paths


def test_no_route_accepts_an_order_submission():
    """The only write endpoints are paper service control and a paper close."""
    writable = sorted(
        f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
        for route in app.routes
        if getattr(route, "methods", None) and route.methods - {"GET", "HEAD", "OPTIONS"}
    )
    assert writable == [
        # Phase 13 learning: request retraining, and approve a promotion. Neither
        # fits a model and neither can place an order.
        "POST /ai/models/{model_id}/approve",
        "POST /ai/retraining/request",
        # Gated manual DEMO execution and its kill switch. No LIVE route exists.
        "POST /execution/demo/propose",
        "POST /execution/demo/test",
        "POST /execution/kill-switch/engage",
        "POST /execution/kill-switch/release",
        # Phase 16 manual approval: a human approves or rejects one proposal.
        "POST /execution/proposals/{proposal_id}/approve",
        "POST /execution/proposals/{proposal_id}/reject",
        # Read-only MT5 session control: opens/closes a data session, never an order.
        "POST /mt5/connect",
        "POST /mt5/disconnect",
        # Phase 12 observation: runs one analysis cycle, sends nothing.
        "POST /observation/cycle",
        "POST /paper/close-position/{position_id}",
        "POST /paper/pause",
        "POST /paper/start",
        "POST /paper/stop",
        # Phase 17: the only validation write. It closes the circuit breaker, and
        # refuses without a health check, a risk check, account validation and a
        # named human. It resumes nothing on its own.
        "POST /validation/circuit-breaker/reset",
        "POST /webhooks/tradingview",
    ]


def test_ai_writes_are_exactly_the_sanctioned_set():
    """No endpoint trains a model; training is an explicit CLI job."""
    writes = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
              for route in app.routes
              if route.path.startswith("/ai") and getattr(route, "methods", None)
              and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert writes == AI_WRITES, writes
    assert not [path for path in writes if "train" in path and "request" not in path]


def test_observation_writes_are_exactly_the_sanctioned_set():
    writes = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
              for route in app.routes
              if route.path.startswith("/observation") and getattr(route, "methods", None)
              and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert writes == OBSERVATION_WRITES, writes


def test_execution_writes_are_exactly_the_sanctioned_set():
    """No execution route beyond the manual DEMO test and the kill switch."""
    writes = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
              for route in app.routes
              if route.path.startswith("/execution") and getattr(route, "methods", None)
              and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert writes == EXECUTION_WRITES, writes


def test_mt5_routes_are_read_only():
    """Every /mt5 route is a GET, apart from read-only session control."""
    writes = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
              for route in app.routes
              if route.path.startswith("/mt5") and getattr(route, "methods", None)
              and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert writes == READ_ONLY_MT5_WRITES, writes


def test_live_environment_is_refused_by_the_execution_engine():
    with pytest.raises(LiveExecutionBlocked):
        PaperExecutionEngine().execute(request(), quote=QUOTE, environment=TradingEnvironment.LIVE)
    with pytest.raises(LiveExecutionBlocked):
        EnvironmentSafetyLock(live_trading_enabled=True).assert_allowed(TradingEnvironment.PAPER)


def test_no_route_can_enable_execution_or_change_the_mode():
    """Phase 16: arming execution is a configuration change, never an API call.

    The mode, the flags and the automation opt-in are all read-only over HTTP, so
    an operator with API access alone cannot move the system out of OBSERVATION.
    """
    forbidden = {"mode", "enable", "arm", "settings", "config"}
    offenders = [route.path for route in app.routes
                 if getattr(route, "methods", None)
                 and route.methods - {"GET", "HEAD", "OPTIONS"}
                 # Segment-wise: "{model_id}" contains "mode" and is not a mode route.
                 and forbidden & set(route.path.lower().split("/"))]
    assert offenders == [], offenders


def test_real_account_execution_is_refused_at_startup():
    from config.settings import Settings

    with pytest.raises(Exception, match="REAL_ACCOUNT_EXECUTION"):
        Settings(database_url="sqlite://",
                 tradingview_webhook_secret="a-secure-test-secret-of-24-chars",
                 real_account_execution=True)


def test_observation_remains_the_default_execution_mode():
    """Section 39: after Phase 16, OBSERVATION is still what ships."""
    settings = get_settings()
    assert settings.execution_mode == "OBSERVATION"
    assert settings.demo_automated_execution_enabled is False
    assert settings.demo_dca_enabled is False
    assert settings.real_account_execution is False
    assert settings.execution_kill_switch is True


def test_validation_endpoints_are_read_only_apart_from_the_breaker_reset():
    """Phase 17: measuring never moves the system."""
    writes = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
              for route in app.routes
              if route.path.startswith("/validation") and getattr(route, "methods", None)
              and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert writes == {"POST /validation/circuit-breaker/reset"}, writes


def test_shadow_mode_is_a_simulation_mode():
    """SHADOW runs the DEMO pipeline and stops one step short of the wire."""
    from execution.demo.modes import BROKER_MODES, SIMULATION_MODES, ExecutionMode

    assert ExecutionMode.SHADOW in SIMULATION_MODES
    assert ExecutionMode.SHADOW not in BROKER_MODES


def test_no_validation_module_imports_an_execution_client():
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "validation"
    forbidden = {"MT5ExecutionClient", "MT5Connection", "PaperExecutionEngine"}
    offenders = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names |= {alias.name for alias in node.names}
            elif isinstance(node, ast.Name):
                names.add(node.id)
        if names & forbidden:
            offenders.append(path.name)
    assert offenders == [], offenders


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
                 if any(token in name.lower() for token in (*FORBIDDEN_ROUTE_TOKENS, "mt5"))]
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
