"""ExecutionGuard — the only authority that may approve an order.

No component calls the MT5 order API directly. `MT5ExecutionClient.send_market_order`
refuses to transmit anything that does not carry a guard approval for that exact
request id, so bypassing the guard is not merely discouraged, it does not work.

The guard is fail-closed: an unknown state is a refusal, and every check that
cannot be evaluated contributes a rejection reason rather than being skipped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from config.settings import Settings, get_settings, load_yaml
from execution.mt5.account import MT5Account, TradeMode
from execution.mt5.kill_switch import ExecutionKillSwitch
from execution.mt5.order_request import ExecutionIntent, OrderRequest, OrderSide
from execution.mt5.order_result import ExecutionRejected, RejectionReason
from features.session import SessionEngine

logger = logging.getLogger(__name__)

DEMO_SERVER_PATTERNS = ("demo", "trial", "practice", "test")


@dataclass(frozen=True, slots=True)
class GuardContext:
    """Everything the guard needs. Anything absent is treated as unsafe."""

    account: MT5Account | None = None
    connected: bool = False
    quote: dict[str, Any] | None = None
    open_positions: int = 0
    dca_entries: int = 0
    exposure: float = 0.0
    daily_drawdown: float = 0.0
    risk_allowed: bool = True
    risk_reasons: tuple[str, ...] = ()
    strategy_status: str | None = None
    known_symbols: tuple[str, ...] = ()
    session: str | None = None
    timestamp: datetime | None = None


@dataclass(frozen=True, slots=True)
class GuardDecision:
    approved: bool
    request_id: str
    reasons: tuple[str, ...] = ()
    checks: dict[str, bool] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    environment: str = "DEMO"

    def as_dict(self) -> dict[str, Any]:
        return {"approved": self.approved, "request_id": self.request_id,
                "reasons": list(self.reasons), "checks": dict(self.checks),
                "timestamp": self.timestamp, "environment": self.environment}


class ExecutionGuard:
    def __init__(self, settings: Settings | None = None, *,
                 kill_switch: ExecutionKillSwitch | None = None,
                 sessions: SessionEngine | None = None):
        self.settings = settings or get_settings()
        config = load_yaml().get("phase_11", {})
        self.kill_switch = kill_switch or ExecutionKillSwitch(
            engaged=bool(getattr(self.settings, "execution_kill_switch", True)),
            reason="CONFIG_DEFAULT",
        )
        self.sessions = sessions or SessionEngine()
        self.demo_server_patterns = tuple(
            str(item).lower() for item in (config.get("demo_server_patterns") or DEMO_SERVER_PATTERNS))
        self.min_volume = float(config.get("min_volume", 0.01))
        self.max_volume = float(min(float(config.get("max_volume", 0.10)),
                                    float(getattr(self.settings, "demo_execution_max_volume", 0.10))))
        self.volume_step = float(config.get("volume_step", 0.01))
        self.max_open_positions = int(config.get("max_open_positions", 3))
        self.max_dca_entries = int(config.get("max_dca_entries", 3))
        self.max_spread = float(config.get("max_spread", 0.0005))
        self.max_daily_drawdown = float(config.get("max_daily_drawdown", 0.03))
        self.max_exposure = float(config.get("max_exposure", 10000))
        self.min_stop_distance = float(config.get("min_stop_distance", 0.0005))
        self.allowed_sessions = tuple(config.get("allowed_sessions") or ())
        self.price_tolerance = float(config.get("price_deviation_tolerance", 0.0020))
        self.symbol_allowlist = self.settings.demo_execution_symbol_allowlist

    # ------------------------------------------------------------------ checks
    def _environment_reasons(self) -> list[str]:
        settings = self.settings
        reasons: list[str] = []
        if str(getattr(settings, "trading_environment", "")).strip().upper() != "DEMO":
            reasons.append(RejectionReason.ENVIRONMENT_NOT_DEMO)
        if getattr(settings, "live_trading_enabled", False):
            reasons.append(RejectionReason.LIVE_TRADING_ENABLED)
        if not getattr(settings, "demo_trading_enabled", False):
            reasons.append(RejectionReason.DEMO_TRADING_DISABLED)
        if not getattr(settings, "mt5_execution_enabled", False):
            reasons.append(RejectionReason.MT5_EXECUTION_DISABLED)
        if getattr(settings, "mt5_read_only", False):
            reasons.append(RejectionReason.MT5_READ_ONLY)
        return reasons

    def _account_reasons(self, context: GuardContext) -> list[str]:
        reasons: list[str] = []
        account = context.account
        if account is None:
            return [RejectionReason.ACCOUNT_UNAVAILABLE]
        if account.trade_mode is TradeMode.REAL:
            reasons.append(RejectionReason.ACCOUNT_IS_REAL)
        elif account.trade_mode not in {TradeMode.DEMO, TradeMode.CONTEST}:
            reasons.append(RejectionReason.ACCOUNT_UNAVAILABLE)
        server = str(account.server or "").lower()
        if not server or not any(pattern in server for pattern in self.demo_server_patterns):
            reasons.append(RejectionReason.SERVER_NOT_DEMO)
        return reasons

    def _volume_reasons(self, request: OrderRequest) -> list[str]:
        reasons: list[str] = []
        volume = request.volume
        if volume is None or volume <= 0 or volume != volume:
            return [RejectionReason.INVALID_VOLUME]
        if volume < self.min_volume:
            reasons.append(RejectionReason.INVALID_VOLUME)
        if volume > self.max_volume:
            reasons.append(RejectionReason.VOLUME_ABOVE_LIMIT)
        # Broker lot steps: 0.013 is not a tradable size.
        steps = round(volume / self.volume_step, 6)
        if abs(steps - round(steps)) > 1e-6:
            reasons.append(RejectionReason.INVALID_VOLUME)
        return reasons

    def _symbol_reasons(self, request: OrderRequest, context: GuardContext) -> list[str]:
        symbol = str(request.symbol or "").strip().upper()
        if not symbol:
            return [RejectionReason.INVALID_SYMBOL]
        if context.known_symbols and symbol not in {s.upper() for s in context.known_symbols}:
            return [RejectionReason.INVALID_SYMBOL]
        if self.symbol_allowlist and symbol not in self.symbol_allowlist:
            return [RejectionReason.SYMBOL_NOT_ALLOWED]
        return []

    def _price_reasons(self, request: OrderRequest, context: GuardContext) -> list[str]:
        reasons: list[str] = []
        quote = context.quote or {}
        bid, ask = quote.get("bid"), quote.get("ask")
        if bid is None or ask is None:
            return [RejectionReason.QUOTE_UNAVAILABLE]
        bid, ask = float(bid), float(ask)
        if bid <= 0 or ask <= 0 or ask < bid:
            return [RejectionReason.INVALID_PRICE]
        if request.price is not None:
            if request.price <= 0:
                reasons.append(RejectionReason.INVALID_PRICE)
            else:
                reference = ask if request.side is OrderSide.BUY else bid
                if abs(float(request.price) - reference) > self.price_tolerance:
                    reasons.append(RejectionReason.PRICE_DEVIATION)
        return reasons

    def _spread_reasons(self, context: GuardContext) -> list[str]:
        quote = context.quote or {}
        bid, ask = quote.get("bid"), quote.get("ask")
        if bid is None or ask is None:
            return [RejectionReason.QUOTE_UNAVAILABLE]
        spread = float(ask) - float(bid)
        return [RejectionReason.SPREAD_TOO_WIDE] if spread > self.max_spread else []

    def _stop_reasons(self, request: OrderRequest, context: GuardContext) -> list[str]:
        """SL must sit the losing side of entry, TP the winning side, both far enough out."""
        reasons: list[str] = []
        quote = context.quote or {}
        bid, ask = quote.get("bid"), quote.get("ask")
        if bid is None or ask is None:
            return []
        entry = float(ask) if request.side is OrderSide.BUY else float(bid)
        buying = request.side is OrderSide.BUY

        if request.sl is not None:
            sl = float(request.sl)
            wrong_side = sl >= entry if buying else sl <= entry
            if sl <= 0 or wrong_side or abs(entry - sl) < self.min_stop_distance:
                reasons.append(RejectionReason.INVALID_STOP_LOSS)
        if request.tp is not None:
            tp = float(request.tp)
            wrong_side = tp <= entry if buying else tp >= entry
            if tp <= 0 or wrong_side or abs(tp - entry) < self.min_stop_distance:
                reasons.append(RejectionReason.INVALID_TAKE_PROFIT)
        return reasons

    def _risk_reasons(self, request: OrderRequest, context: GuardContext) -> list[str]:
        reasons: list[str] = []
        if not context.risk_allowed:
            reasons.append(RejectionReason.RISK_BLOCKED)
        if context.daily_drawdown >= self.max_daily_drawdown:
            reasons.append(RejectionReason.DAILY_DRAWDOWN_EXCEEDED)
        if context.exposure >= self.max_exposure:
            reasons.append(RejectionReason.MAXIMUM_EXPOSURE)
        if request.intent is ExecutionIntent.DCA:
            if context.dca_entries >= self.max_dca_entries:
                reasons.append(RejectionReason.DCA_LIMIT)
        elif context.open_positions >= self.max_open_positions:
            reasons.append(RejectionReason.POSITION_LIMIT)
        return reasons

    def _session_reasons(self, context: GuardContext) -> list[str]:
        if not self.allowed_sessions:
            return []
        moment = context.timestamp or datetime.now(timezone.utc)
        session = context.session or self.sessions.session_for(moment).value
        return [] if session in self.allowed_sessions else [RejectionReason.SESSION_NOT_ALLOWED]

    def _strategy_reasons(self, request: OrderRequest, context: GuardContext) -> list[str]:
        """A manual test carries no strategy; a strategy-driven order must be executable."""
        if request.intent is ExecutionIntent.MANUAL_TEST:
            return []
        if context.strategy_status != "EXECUTABLE_SIMULATION":
            return [RejectionReason.STRATEGY_NOT_EXECUTABLE]
        return []

    # ------------------------------------------------------------------ verdict
    def evaluate(self, request: OrderRequest, context: GuardContext | None = None) -> GuardDecision:
        context = context or GuardContext()
        new_entry = request.intent is not ExecutionIntent.DCA
        blocked_by_switch = self.kill_switch.blocking_reasons(
            new_entry=new_entry, increases_exposure=not new_entry)
        groups: dict[str, list[str]] = {
            "environment": self._environment_reasons(),
            "kill_switch": [RejectionReason.KILL_SWITCH_ENGAGED] if blocked_by_switch else [],
            "connection": [] if context.connected else [RejectionReason.NOT_CONNECTED],
            "account": self._account_reasons(context),
            "symbol": self._symbol_reasons(request, context),
            "volume": self._volume_reasons(request),
            "price": self._price_reasons(request, context),
            "spread": self._spread_reasons(context),
            "stops": self._stop_reasons(request, context),
            "risk": self._risk_reasons(request, context),
            "session": self._session_reasons(context),
            "strategy": self._strategy_reasons(request, context),
        }
        reasons: list[str] = []
        for group in groups.values():
            for reason in group:
                if reason not in reasons:
                    reasons.append(str(reason))
        checks = {name: not group for name, group in groups.items()}
        decision = GuardDecision(
            not reasons, request.request_id, tuple(reasons), checks,
            environment=self.settings.environment,
        )
        if reasons:
            logger.info("execution refused for %s: %s", request.request_id, ", ".join(reasons))
        return decision

    def assert_allowed(self, request: OrderRequest, context: GuardContext | None = None) -> GuardDecision:
        decision = self.evaluate(request, context)
        if not decision.approved:
            raise ExecutionRejected(decision.reasons)
        return decision
