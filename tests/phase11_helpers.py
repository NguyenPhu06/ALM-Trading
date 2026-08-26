"""Shared fixtures for Phase 11 DEMO execution tests."""
from __future__ import annotations

from typing import Any

from config.settings import Settings
from database.repositories import AlertRepository
from database.repositories.execution import ExecutionRepository
from execution.mt5.execution_client import MT5ExecutionClient
from execution.mt5.execution_guard import ExecutionGuard, GuardContext
from execution.mt5.execution_service import DemoExecutionService
from execution.mt5.kill_switch import ExecutionKillSwitch
from execution.mt5.mock import FakeExecutionModule, MockMT5ReadOnlyClient
from execution.mt5.order_request import ExecutionIntent, OrderRequest, OrderSide, OrderType
from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter

BASE = dict(database_url="sqlite://", tradingview_webhook_secret="a-secure-test-secret-of-24-chars")
DEMO_SERVER = "Exness-MT5Trial8"
REAL_TRADE_MODE = 2


def settings(**overrides: Any) -> Settings:
    """Default = every gate closed. Pass armed=True for the fully open posture."""
    if overrides.pop("armed", False):
        overrides.setdefault("demo_trading_enabled", True)
        overrides.setdefault("mt5_execution_enabled", True)
        overrides.setdefault("mt5_read_only", False)
        overrides.setdefault("execution_kill_switch", False)
    return Settings(**BASE, **overrides)


def armed() -> Settings:
    return settings(armed=True)


def order(**overrides: Any) -> OrderRequest:
    payload: dict[str, Any] = dict(
        symbol="EURUSD", side=OrderSide.BUY, volume=0.01, order_type=OrderType.MARKET,
        sl=1.09000, tp=1.11000, intent=ExecutionIntent.MANUAL_TEST,
    )
    payload.update(overrides)
    return OrderRequest(**payload)


def guard_for(config: Settings | None = None, *, engaged: bool | None = None) -> ExecutionGuard:
    config = config or armed()
    switch = ExecutionKillSwitch(
        engaged=config.execution_kill_switch if engaged is None else engaged, reason="TEST")
    return ExecutionGuard(config, kill_switch=switch)


def context(**overrides: Any) -> GuardContext:
    """A context that passes every check, so a test can break exactly one thing."""
    from execution.mt5.account import MT5Account, TradeMode

    account = overrides.pop("account", MT5Account(
        login=987654321, server=DEMO_SERVER, broker="Exness", currency="USD",
        balance=10000.0, equity=10000.0, margin=0.0, free_margin=10000.0,
        margin_level=0.0, trade_mode=TradeMode.DEMO))
    base: dict[str, Any] = dict(
        account=account, connected=True,
        quote={"bid": 1.10012, "ask": 1.10024, "mid_price": 1.10018},
        open_positions=0, dca_entries=0, exposure=0.0, daily_drawdown=0.0,
        risk_allowed=True, strategy_status="EXECUTABLE_SIMULATION",
        known_symbols=("EURUSD", "GBPUSD"), session="LONDON",
    )
    base.update(overrides)
    return GuardContext(account=account, **{k: v for k, v in base.items() if k != "account"})


def service_for(db_session, config: Settings | None = None, *,
                module: FakeExecutionModule | None = None,
                with_alerts: bool = True) -> tuple[DemoExecutionService, FakeExecutionModule]:
    config = config or armed()
    fake = module or FakeExecutionModule(server=DEMO_SERVER)
    read_client = MockMT5ReadOnlyClient(config, module=fake)
    read_client.connect()
    execution_client = MT5ExecutionClient(config, connection=read_client.connection,
                                          read_client=read_client)
    router = None
    if with_alerts:
        router = AlertRouter(AlertEngine(AlertRepositoryNotificationProvider(
            AlertRepository(db_session))))
    service = DemoExecutionService(
        db_session, guard=guard_for(config), client=execution_client,
        read_client=read_client, repository=ExecutionRepository(db_session),
        alerts=router, settings=config,
    )
    return service, fake
