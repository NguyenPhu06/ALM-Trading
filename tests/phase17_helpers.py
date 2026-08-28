"""Shared fixtures for Phase 17 shadow trading and DEMO validation tests.

Everything is deterministic and terminal-free. The Phase 16 helpers already build
a real service over `FakeExecutionModule`; these add the shadow-side scaffolding
and the populations the validation modules consume.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from config.settings import Settings
from execution.demo.order import DemoOrderRequest
from tests.phase16_helpers import (
    APPROVAL_MOMENT, BASE, DEMO_SERVER, LONDON_MOMENT, armed, chain_for, context,
    demo_account, live_context, manual, order, service_for, settings,
)
from validation.circuit_breaker import BreakerSignals, CircuitBreaker, RecoveryChecklist
from validation.shadow import ShadowRecorder, ShadowSignal

SHADOW_MOMENT = LONDON_MOMENT
EXIT_MOMENT = LONDON_MOMENT + timedelta(hours=2)


def shadow_settings(**overrides: Any) -> Settings:
    """SHADOW mode: the DEMO pipeline exactly, minus the broker call."""
    overrides.setdefault("demo_execution_mode", "SHADOW")
    return settings(**overrides)


def recorder(repository: Any = None, **kwargs: Any) -> ShadowRecorder:
    kwargs.setdefault("spread_cost", 0.0001)
    kwargs.setdefault("slippage_estimate", 0.00002)
    kwargs.setdefault("commission", 0.0)
    return ShadowRecorder(repository, **kwargs)


def shadow_signal(*, request: DemoOrderRequest | None = None, decision: Any = None,
                  ctx: Any = None, recorder_: ShadowRecorder | None = None,
                  **overrides: Any) -> ShadowSignal:
    """A shadow record minted the way the service mints one: from a real decision."""
    request = request or order()
    ctx = ctx if ctx is not None else context()
    decision = decision if decision is not None else chain_for(armed()).evaluate(request, ctx)
    return (recorder_ or recorder()).record(request, decision, ctx, **overrides)


def breaker(**kwargs: Any) -> CircuitBreaker:
    kwargs.setdefault("settings", armed())
    return CircuitBreaker(**kwargs)


def full_checklist(**overrides: Any) -> RecoveryChecklist:
    payload = dict(health_check=True, risk_check=True, account_validation=True,
                   approved_by="Phu", reason="verified demo account and healthy feed")
    payload.update(overrides)
    return RecoveryChecklist(**payload)


def trades(count: int = 40, *, net_pnl: float = 1.0, alternate: bool = True,
           regime: str = "BULL", session: str = "LONDON", timeframe: str = "M5",
           signal_timeframe: str = "H1", start: datetime | None = None,
           step: timedelta = timedelta(hours=1), **extra: Any) -> list[dict[str, Any]]:
    """A resolved population for the segment, window and gate evaluators.

    `alternate` makes every third trade a loser so a population has both wins and
    losses; a population of only winners would clear the sample floors while
    telling you nothing.
    """
    moment = start or (LONDON_MOMENT - step * count)
    rows: list[dict[str, Any]] = []
    for index in range(count):
        losing = alternate and index % 3 == 2
        rows.append({
            "timestamp": moment + step * index,
            "net_pnl": -abs(net_pnl) if losing else abs(net_pnl),
            "mae": -0.0008, "mfe": 0.0031, "spread": 0.00012, "slippage": 0.00005,
            "regime": regime, "session": session, "timeframe": timeframe,
            "signal_timeframe": signal_timeframe, "symbol": "EURUSD",
            "side": "SELL" if index % 2 else "BUY", "confidence": 0.7,
            **extra,
        })
    return rows


def predictions(count: int = 40, *, accuracy: float = 0.6, confidence: float = 0.7,
                **extra: Any) -> list[dict[str, Any]]:
    """Scored predictions: `accuracy` of them are right, the rest are wrong."""
    correct = int(round(count * accuracy))
    rows = []
    for index in range(count):
        right = index < correct
        rows.append({"predicted": "UP", "actual": "UP" if right else "DOWN",
                     "confidence": confidence, **extra})
    return rows


def execution_records(count: int = 40, *, rejected: int = 0, errored: int = 0,
                      slippage: float = 0.0001, spread: float = 0.00012,
                      latency_ms: float = 40.0) -> list[dict[str, Any]]:
    rows = []
    for index in range(count):
        if index < rejected:
            status = "REJECTED"
        elif index < rejected + errored:
            status = "FAILED"
        else:
            status = "FILLED"
        rows.append({"status": status, "slippage": slippage, "spread": spread,
                     "latency_ms": latency_ms})
    return rows
