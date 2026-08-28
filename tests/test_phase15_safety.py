"""Phase 15 mandatory safety tests (section 26).

    Research execution must:
      NEVER send MT5 orders
      NEVER modify MT5 positions
      NEVER enable execution
      NEVER disable kill switch

Asserted twice where possible: behaviourally (run every study, compare the flags)
and structurally (parse every module in the package).
"""
import ast
import pathlib

import pytest

from api.main import app
from config.settings import get_settings
from research import (
    AblationStudy,
    ConflictEngine,
    DCAResearch,
    ErrorLab,
    ExitResearch,
    ExperimentLedger,
    ExperimentRunner,
    HoldoutGuard,
    LiquidityEventStudy,
    MatrixBuilder,
    NNValueTest,
    ResearchReporter,
    SignalWeightResearch,
    SignificanceTester,
    StrategyChallengerEvaluator,
    StrategyRegistry,
    catalogue,
    configured,
    strategy,
)
from tests.phase15_helpers import ablation_arms, series, validated

SAFETY_FLAGS = ("live_trading_enabled", "demo_trading_enabled", "mt5_execution_enabled",
                "execution_kill_switch", "observation_mode", "ai_auto_promote",
                "ai_online_learning_enabled", "ai_automatic_training")

EXECUTION_TOKENS = ("order_send", "send_market_order", "MT5ExecutionClient",
                    "DemoExecutionService", "ExecutionGuard", "ExecutionKillSwitch",
                    "PaperExecutionEngine", "position_close", "position_modify",
                    "order_check", "MT5ReadOnlyClient")

RESEARCH_MODULES = sorted(path.as_posix()
                          for path in pathlib.Path("research").glob("*.py"))


def flags():
    settings = get_settings()
    return {name: getattr(settings, name) for name in SAFETY_FLAGS}


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


# ------------------------------------------------------ the package cannot trade
def test_the_research_package_has_modules_to_check():
    assert len(RESEARCH_MODULES) >= 15


@pytest.mark.parametrize("module", RESEARCH_MODULES)
def test_no_research_module_references_an_execution_symbol(module):
    names = identifiers(pathlib.Path(module).read_text(encoding="utf-8"))
    offenders = [token for token in EXECUTION_TOKENS
                 if token in names or any(name.endswith(f".{token}") for name in names)]
    assert offenders == [], f"{module}: {offenders}"


@pytest.mark.parametrize("module", RESEARCH_MODULES)
def test_no_research_module_imports_an_execution_package(module):
    names = identifiers(pathlib.Path(module).read_text(encoding="utf-8"))
    forbidden = [name for name in names
                 if name.startswith("execution") or name.startswith("paper")]
    assert forbidden == [], f"{module}: {forbidden}"


@pytest.mark.parametrize("module", RESEARCH_MODULES)
def test_no_research_module_writes_a_setting(module):
    source = pathlib.Path(module).read_text(encoding="utf-8")
    for token in ("live_trading_enabled =", "demo_trading_enabled =",
                  "mt5_execution_enabled =", "execution_kill_switch =",
                  "observation_mode ="):
        assert token not in source, f"{module}: {token}"


def test_the_research_package_docstring_states_it_does_not_execute():
    import research

    assert "Nothing in this package executes" in research.__doc__


# ------------------------------------------- 26. running research changes nothing
def test_running_every_study_leaves_every_flag_untouched():
    before = flags()

    rows = series(200, seed=1)
    ledger = ExperimentLedger()
    runner = ExperimentRunner(minimum_samples=30, ledger=ledger)
    for config in catalogue():
        runner.run(config, rows)

    AblationStudy(minimum_samples=30).run(ablation_arms(count=120))
    MatrixBuilder(minimum_samples=30).all(rows)
    DCAResearch(minimum_samples=30).run(rows)
    ExitResearch(minimum_samples=30).run(rows)
    NNValueTest(minimum_samples=50).split(rows)
    LiquidityEventStudy(minimum_samples=30).run(rows)
    ConflictEngine().study(rows, minimum_samples=30)
    SignalWeightResearch(minimum_samples=30).run(rows)
    ErrorLab(minimum_samples=30).run(rows)
    SignificanceTester(minimum_samples=50).absolute([row.net_pnl for row in rows])

    guard = HoldoutGuard(ledger=ledger)
    research_rows, holdout = guard.split(rows)
    guard.peek(holdout, reason="final evaluation")

    StrategyChallengerEvaluator(minimum_samples=50).evaluate(
        champion=series(100, mean=0.0002, seed=2),
        challenger=series(100, mean=0.0009, seed=3, start=1000),
        challenger_windows=[0.6, 0.62, 0.61])

    assert flags() == before


def test_promoting_a_strategy_changes_no_execution_flag():
    from research.registry import ApprovalToken

    before = flags()
    registry = StrategyRegistry()
    registry.register(strategy("smc", "candidate", features=("liquidity",)))
    validated(registry, "smc:v1")
    registry.promote("smc:v1", ApprovalToken("nvphu", "safety check"))
    assert flags() == before


def test_writing_reports_changes_no_flag(tmp_path):
    before = flags()
    ResearchReporter(tmp_path).generate({"regime_analysis": {"best": "BULL"}})
    assert flags() == before


def test_no_study_result_claims_an_order_was_sent():
    result = ExperimentRunner().run(configured("smc"), series(60, seed=4))
    assert result.as_dict()["orders_sent"] == 0


def test_the_challenger_report_never_reports_itself_as_promoted():
    report = StrategyChallengerEvaluator(minimum_samples=50).evaluate(
        champion=series(100, mean=0.0002, seed=5),
        challenger=series(100, mean=0.0009, seed=6, start=1000),
        challenger_windows=[0.6, 0.62, 0.61])
    assert report.promoted is False
    assert report.as_dict()["requires_human_approval"] is True


# ------------------------------------------------------------ shipped defaults
def test_the_shipped_defaults_are_unchanged_by_phase_15():
    settings = get_settings()
    assert settings.live_trading_enabled is False
    assert settings.demo_trading_enabled is False
    assert settings.mt5_execution_enabled is False
    assert settings.execution_kill_switch is True
    assert settings.observation_mode is True
    assert settings.ai_auto_promote is False
    assert settings.ai_online_learning_enabled is False
    assert settings.ai_automatic_training is False


def test_the_research_job_refuses_to_run_with_an_execution_gate_open():
    from types import SimpleNamespace

    from scripts.run_research_lab import UnsafeConfiguration, _refuse_unless_safe

    unsafe = SimpleNamespace(live_trading_enabled=True, demo_trading_enabled=True,
                             mt5_execution_enabled=True, execution_kill_switch=False)
    with pytest.raises(UnsafeConfiguration) as error:
        _refuse_unless_safe(unsafe)
    message = str(error.value)
    for token in ("LIVE_TRADING_ENABLED", "DEMO_TRADING_ENABLED",
                  "MT5_EXECUTION_ENABLED", "EXECUTION_KILL_SWITCH_RELEASED"):
        assert token in message


def test_the_research_job_starts_with_the_shipped_settings():
    from scripts.run_research_lab import _refuse_unless_safe

    assert _refuse_unless_safe(get_settings()) is None


# --------------------------------------------------------------- API surface
def test_phase_15_adds_no_write_route():
    writes = {f"{sorted(route.methods - {'HEAD', 'OPTIONS'})[0]} {route.path}"
              for route in app.routes if getattr(route, "methods", None)
              and route.methods - {"GET", "HEAD", "OPTIONS"}}
    assert not [path for path in writes if "research" in path]


def test_the_research_dashboard_states_the_invariants(client):
    payload = client.get("/dashboard/research").json()["data"]
    assert payload["orders_sent"] == 0
    assert payload["automated_trading"] is False
    assert payload["promoted_automatically"] is False
    assert payload["requires_human_approval"] is True
    assert payload["evidence"] == "FORWARD_OBSERVATION"


def test_the_strategy_endpoint_says_a_registry_entry_does_not_execute(client):
    payload = client.get("/research/strategies").json()
    assert payload["executes"] is False
    assert payload["promotion_requires_approval"] is True


def test_the_champion_endpoint_states_no_automatic_promotion(client):
    payload = client.get("/research/champion").json()
    assert payload["promoted_automatically"] is False
    assert payload["requires_human_approval"] is True
    assert payload["criteria"]
