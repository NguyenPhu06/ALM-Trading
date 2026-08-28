"""Shared fixtures for Phase 16 controlled DEMO trading tests.

Everything here is deterministic and terminal-free: `FakeExecutionModule` is
driven through the real `MT5Connection`, `MT5ReadOnlyClient` and
`MT5ExecutionClient`, so the tests exercise the production code paths rather
than a parallel implementation (section 34).

`settings()` ships every gate closed, which is the real default. Pass
`armed=True` for the fully open DEMO_AUTOMATED posture, or `mode=` for one of
the other four modes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config.settings import Settings
from database.repositories import AlertRepository
from database.repositories.demo import DemoTradingRepository
from database.repositories.execution import ExecutionRepository
from execution.demo.daily_risk import DailyRiskState, DailyRiskTracker
from execution.demo.gates import DemoExecutionContext, DemoGateChain
from execution.demo.limits import DemoRiskLimits
from execution.demo.order import DemoOrderRequest
from execution.demo.service import ControlledDemoTradingService
from execution.mt5.execution_client import MT5ExecutionClient
from execution.mt5.execution_guard import ExecutionGuard
from execution.mt5.kill_switch import ExecutionKillSwitch
from execution.mt5.mock import FakeExecutionModule, MockMT5ReadOnlyClient
from execution.mt5.order_request import ExecutionIntent, OrderSide, OrderType
from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter
from observation.demo_account import DemoAccountResult, DemoValidation

BASE = dict(database_url="sqlite://", tradingview_webhook_secret="a-secure-test-secret-of-24-chars")
DEMO_SERVER = "Exness-MT5Trial8"
REAL_TRADE_MODE = 2
UNKNOWN_TRADE_MODE = 7
# A London-session instant, so SessionGate and the Phase 11 guard are not at the
# mercy of what time the suite happens to run.
LONDON_MOMENT = datetime(2026, 8, 27, 10, 30, tzinfo=timezone.utc)
# A moment inside the proposal TTL. Approving at wall-clock "now" would make a
# manual-approval test pass only on the day it was written.
APPROVAL_MOMENT = datetime(2026, 8, 27, 10, 35, tzinfo=timezone.utc)


def settings(**overrides: Any) -> Settings:
    """Default = every gate closed and OBSERVATION mode, which is what ships."""
    if overrides.pop("armed", False):
        overrides.setdefault("demo_execution_mode", "DEMO_AUTOMATED")
        overrides.setdefault("demo_automated_execution_enabled", True)
    mode = str(overrides.get("demo_execution_mode", "OBSERVATION")).upper()
    if mode in {"DEMO_AUTOMATED", "DEMO_MANUAL_APPROVAL"}:
        overrides.setdefault("demo_trading_enabled", True)
        overrides.setdefault("mt5_execution_enabled", True)
        overrides.setdefault("mt5_read_only", False)
        overrides.setdefault("execution_kill_switch", False)
    return Settings(**BASE, **overrides)


def armed(**overrides: Any) -> Settings:
    return settings(armed=True, **overrides)


def manual(**overrides: Any) -> Settings:
    return settings(demo_execution_mode="DEMO_MANUAL_APPROVAL", **overrides)


def order(**overrides: Any) -> DemoOrderRequest:
    """A well-formed, correctly sized request that every gate should accept."""
    payload: dict[str, Any] = dict(
        symbol="EURUSD", side=OrderSide.BUY, volume=0.02, signal_id="signal-001",
        trading_day="2026-08-27", price=1.10024, stop_loss=1.09500, take_profit=1.11000,
        order_type=OrderType.MARKET, strategy_id="smc", strategy_version="phase6.strategy.v1",
        model_version="model-1", feature_version="features_v1", risk_snapshot_id="risk-1",
        reason="TEST", intent=ExecutionIntent.NEW_ENTRY, timestamp=LONDON_MOMENT,
        risk_percent=0.005, risk_amount=50.0, stop_distance=0.00524,
    )
    payload.update(overrides)
    return DemoOrderRequest.build(**payload)


def demo_account(**overrides: Any) -> DemoAccountResult:
    from execution.mt5.account import MT5Account, TradeMode

    account = overrides.pop("account", MT5Account(
        login=987654321, server=DEMO_SERVER, broker="Exness", currency="USD",
        balance=10000.0, equity=10000.0, margin=0.0, free_margin=10000.0,
        margin_level=0.0, trade_mode=TradeMode.DEMO))
    status = overrides.pop("status", DemoValidation.VALID_DEMO)
    reasons = overrides.pop("reasons", ("ACCOUNT_IS_DEMO",))
    return DemoAccountResult(status, reasons, account, None)


def daily_state(**overrides: Any) -> DailyRiskState:
    tracker = DailyRiskTracker()
    state = tracker.update(equity=float(overrides.pop("equity", 10000.0)),
                           moment=overrides.pop("moment", LONDON_MOMENT))
    if overrides:
        from dataclasses import replace

        state = replace(state, **overrides)
    return state


def context(**overrides: Any) -> DemoExecutionContext:
    """A context that passes every gate, so a test can break exactly one thing."""
    base: dict[str, Any] = dict(
        account=demo_account(), connected=True,
        quote={"bid": 1.10012, "ask": 1.10024, "mid_price": 1.10018},
        data_quality_ok=True, data_age_seconds=5.0,
        risk_allowed=True, risk_snapshot_id="risk-1",
        equity=10000.0, free_margin=10000.0, used_margin=0.0,
        daily=daily_state(), open_positions=0,
        symbol_exposure=0.0, total_exposure=0.0, order_notional=2200.0,
        dca_levels=0, dca_exposure=0.0,
        strategy_status="CHAMPION", strategy_decision="EXECUTABLE_SIMULATION",
        strategy_id="smc", model_confidence=0.72, model_direction_probability=0.71,
        expected_slippage=0.00001, session="LONDON",
        known_symbols=("EURUSD", "GBPUSD"), timestamp=LONDON_MOMENT,
    )
    base.update(overrides)
    return DemoExecutionContext(**base)


def chain_for(config: Settings | None = None, *, engaged: bool | None = None,
              limits: DemoRiskLimits | None = None) -> DemoGateChain:
    config = config or armed()
    switch = ExecutionKillSwitch(
        engaged=config.execution_kill_switch if engaged is None else engaged, reason="TEST")
    guard = ExecutionGuard(config, kill_switch=switch)
    return DemoGateChain(config, guard=guard, limits=limits)


def service_for(db_session, config: Settings | None = None, *,
                module: FakeExecutionModule | None = None,
                with_alerts: bool = True,
                limits: DemoRiskLimits | None = None,
                ) -> tuple[ControlledDemoTradingService, FakeExecutionModule]:
    config = config or armed()
    fake = module or FakeExecutionModule(server=DEMO_SERVER, now=LONDON_MOMENT)
    read_client = MockMT5ReadOnlyClient(config, module=fake)
    read_client.connect()
    execution_client = MT5ExecutionClient(config, connection=read_client.connection,
                                          read_client=read_client)
    router = None
    if with_alerts:
        router = AlertRouter(AlertEngine(AlertRepositoryNotificationProvider(
            AlertRepository(db_session))))
    chain = chain_for(config, limits=limits)
    service = ControlledDemoTradingService(
        db_session, settings=config, chain=chain, guard=chain.guard, client=execution_client,
        read_client=read_client, repository=ExecutionRepository(db_session),
        demo_repository=DemoTradingRepository(db_session), alerts=router, limits=limits,
    )
    return service, fake


def live_context(service: ControlledDemoTradingService, request: DemoOrderRequest,
                 **overrides: Any) -> DemoExecutionContext:
    """The service's own context, topped up with the parts only a caller knows.

    Data quality, the risk verdict, the strategy status and the model reading
    come from upstream engines; the service reads the account, the quote and the
    positions itself.
    """
    payload: dict[str, Any] = dict(
        data_quality_ok=True, data_age_seconds=5.0, risk_allowed=True,
        risk_snapshot_id="risk-1", strategy_status="CHAMPION",
        strategy_decision="EXECUTABLE_SIMULATION", strategy_id="smc",
        model_confidence=0.72, model_direction_probability=0.71, session="LONDON",
    )
    payload.update(overrides)
    return service.build_context(request, **payload)
