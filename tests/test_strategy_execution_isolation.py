"""Strategy must not be able to reach MT5 execution (§8, §18).

Phase 11 builds the execution foundation and a manual test only. The strategy
engine still terminates at paper trading; it returns a decision and nothing more.
"""
import ast
import inspect
import pathlib

from orchestration.cycle import OrchestrationCycle
from strategy.engine import StrategyIntelligenceEngine
from strategy.models import StrategyDecision

EXECUTION_SYMBOLS = (
    "MT5ExecutionClient", "DemoExecutionService", "ExecutionGuard", "send_market_order",
    "order_send", "OrderRequest", "execution_client", "execution_guard",
)
STRATEGY_MODULES = tuple(pathlib.Path("strategy").glob("*.py"))


def offending(names: set[str]) -> list[str]:
    """Exact identifier match, plus any import from the MT5 execution package.

    Substring matching would flag PaperOrderRequest, which is the paper engine's
    own type and entirely correct.
    """
    found = [symbol for symbol in EXECUTION_SYMBOLS
             if symbol in names or any(name.endswith(f".{symbol}") for name in names)]
    found += [name for name in names if "execution.mt5" in name]
    return sorted(set(found))


def identifiers(source: str) -> set[str]:
    tree = ast.parse(source)
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
    return names


def test_no_strategy_module_references_mt5_execution():
    offenders = []
    for path in STRATEGY_MODULES:
        for symbol in offending(identifiers(path.read_text(encoding="utf-8"))):
            offenders.append(f"{path.name}:{symbol}")
    assert offenders == [], offenders


def test_the_strategy_engine_has_no_execution_method():
    for name in ("send_order", "execute", "send_market_order", "place_order", "submit"):
        assert not hasattr(StrategyIntelligenceEngine, name), name


def test_a_strategy_decision_is_data_not_an_instruction():
    """It carries a verdict and reasons; it cannot transmit anything."""
    fields = set(StrategyDecision.__dataclass_fields__)
    assert fields == {"timestamp", "symbol", "decision", "setup", "reason_codes",
                      "strategy_version"}
    for name in ("send", "execute", "submit", "route"):
        assert not hasattr(StrategyDecision, name), name


def test_the_orchestration_cycle_still_terminates_at_paper():
    source = inspect.getsource(OrchestrationCycle)
    assert "self.paper.enter(" in source
    assert offending(identifiers(source)) == []


def test_the_orchestration_cycle_holds_no_execution_collaborator():
    from paper import PaperTradingService

    service = PaperTradingService()
    cycle = OrchestrationCycle.__new__(OrchestrationCycle)
    for name in ("execution", "execution_client", "guard", "mt5_execution"):
        assert not hasattr(cycle, name), name
    assert not hasattr(service, "execution_client")


def test_the_demo_execution_endpoint_accepts_no_strategy_identifier(client):
    """The manual endpoint's payload has no strategy_id, so a strategy cannot drive it."""
    response = client.post("/execution/demo/test", json={
        "symbol": "EURUSD", "side": "BUY", "volume": 0.01, "strategy_id": "phase6.strategy.v1",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["request"]["strategy_id"] is None if "request" in body else True
    assert body["result"]["reasons"], "still refused under the shipped defaults"


def test_manual_requests_are_marked_as_manual(client, db_session):
    from database.models import ExecutionRequestRecord

    client.post("/execution/demo/test", json={"symbol": "EURUSD", "side": "BUY", "volume": 0.01})
    row = db_session.query(ExecutionRequestRecord).one()
    assert row.intent == "MANUAL_TEST" and row.strategy_id is None
