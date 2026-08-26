"""MT5ReadOnlyClient — the only MT5 surface the rest of ALM-Trading may use.

This class deliberately defines NO execution methods. `hasattr(client, "send_order")`
is False, and there is no code path from here to `order_send`. An adapter that must
satisfy a broader interface uses `ReadOnlyExecutionGuard`, whose methods raise
`ReadOnlyModeError`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from config.settings import Settings, get_settings, load_yaml
from execution.mt5.account import (
    AccountValidation,
    AccountValidator,
    MT5Account,
    account_from_mt5,
)
from execution.mt5.connection import (
    MT5_CREDENTIALS_MISSING,
    MT5_TERMINAL_NOT_AVAILABLE,
    ConnectionReport,
    ConnectionState,
    MT5Connection,
    mask_login,
)
from execution.mt5.health import HealthReport, MT5HealthMonitor
from execution.mt5.history import HistoryReader, MT5Deal, MT5Order
from execution.mt5.market_data import (
    SUPPORTED_TIMEFRAMES,
    MT5MarketDataReader,
    SpreadMonitor,
    mt5_timeframe,
)
from execution.mt5.positions import MT5Position, PositionReader
from execution.mt5.safety import MT5SafetyLock, ReadOnlyModeError
from execution.mt5.symbols import SymbolInfo, SymbolResolutionError, SymbolResolver

logger = logging.getLogger(__name__)

ACCOUNT_BLOCKED = "ACCOUNT_BLOCKED"


@dataclass(frozen=True, slots=True)
class ReadResult:
    """Uniform envelope so a caller never has to distinguish empty from unavailable."""

    ok: bool
    data: Any = None
    code: str = "OK"
    reasons: tuple[str, ...] = ()

    @classmethod
    def failure(cls, code: str, *reasons: str) -> "ReadResult":
        return cls(False, None, code, tuple(reasons) or (code,))


class MT5ReadOnlyClient:
    """Read-only MetaTrader 5 access for a DEMO account."""

    def __init__(self, settings: Settings | None = None, *, connection: MT5Connection | None = None,
                 safety: MT5SafetyLock | None = None, reader: MT5MarketDataReader | None = None,
                 broker: str | None = None, now: datetime | None = None):
        self.settings = settings or get_settings()
        self.safety = safety or MT5SafetyLock(self.settings)
        self.connection = connection or MT5Connection(self.settings, safety=self.safety)
        config = load_yaml().get("phase_10", {})
        spread = config.get("spread", {})
        self.reader = reader or MT5MarketDataReader(spread_monitor=SpreadMonitor(
            window=int(spread.get("average_window", 50)),
            elevated_ratio=float(spread.get("elevated_ratio", 1.5)),
            extreme_ratio=float(spread.get("extreme_ratio", 3.0)),
        ))
        self.broker = broker or self.settings.mt5_broker
        self.timeframes = tuple(config.get("timeframes") or SUPPORTED_TIMEFRAMES)
        self.default_count = int(config.get("default_candle_count", 500))
        self.validator = AccountValidator()
        self.positions_reader = PositionReader(alm_magic_number=self.settings.mt5_magic_number)
        self.history_reader = HistoryReader(reader=self.positions_reader)
        self.health_monitor = MT5HealthMonitor(
            tick_stale_seconds=float(config.get("tick_stale_seconds", 30)),
            candle_stale_multiplier=float(config.get("candle_stale_multiplier", 3)),
        )
        self.canonical_symbols = tuple(config.get("canonical_symbols") or ())
        # Injectable clock: tests pin it, production reads the wall clock.
        self._clock = now
        self._resolver: SymbolResolver | None = None
        self._account: MT5Account | None = None
        self._validation: AccountValidation | None = None
        self._last_tick: dict[str, datetime] = {}
        self._last_candle: dict[tuple[str, str], datetime] = {}

    def now(self) -> datetime:
        return self._clock or datetime.now(timezone.utc)

    # ------------------------------------------------------------------ module
    @property
    def module(self) -> Any | None:
        return self.connection.module

    def _guard(self) -> ReadResult | None:
        """Safety lock, then terminal, then account validity. Returns None when clear."""
        decision = self.safety.evaluate_data_access()
        if not decision.allowed:
            return ReadResult.failure(str(decision.block), *decision.reasons)
        if self.module is None or not self.connection.is_connected():
            return ReadResult.failure(MT5_TERMINAL_NOT_AVAILABLE)
        if self._validation is not None and not self._validation.allowed:
            return ReadResult.failure(ACCOUNT_BLOCKED, *self._validation.reasons)
        return None

    # -------------------------------------------------------------- lifecycle
    def connect(self) -> ConnectionReport:
        """Open a read-only session and validate the account is DEMO.

        A REAL account is disconnected immediately and no data is read from it.
        """
        if not self.settings.mt5_credentials_present() and not self.settings.mt5_terminal_path:
            logger.info("MT5 credentials not configured; attempting attach to a running terminal")
        report = self.connection.connect()
        if report.state is not ConnectionState.CONNECTED:
            return report
        account = self._read_account()
        self._account = account
        self._validation = self.validator.validate(account)
        if not self._validation.allowed:
            logger.error("MT5 account refused: %s", ", ".join(self._validation.reasons))
            self.connection.disconnect()
            return ConnectionReport(
                ConnectionState.BLOCKED, datetime.now(timezone.utc), ACCOUNT_BLOCKED,
                self._validation.reasons, report.terminal, report.server, report.masked_login,
                {"trade_mode": str(self._validation.trade_mode)},
            )
        return report

    def disconnect(self) -> ConnectionReport:
        self._account = None
        self._validation = None
        self._resolver = None
        return self.connection.disconnect()

    def is_connected(self) -> bool:
        return self.connection.is_connected() and bool(self._validation and self._validation.allowed)

    # ---------------------------------------------------------------- account
    def _read_account(self) -> MT5Account | None:
        try:
            raw = self.module.account_info()
        except Exception:
            logger.exception("MT5 account_info failed")
            return None
        if raw is None:
            return None
        return account_from_mt5(raw, broker=self.broker)

    def get_account(self) -> ReadResult:
        blocked = self._guard()
        if blocked is not None and blocked.code != ACCOUNT_BLOCKED:
            return blocked
        account = self._read_account()
        if account is None:
            return ReadResult.failure("ACCOUNT_UNAVAILABLE")
        validation = self.validator.validate(account)
        self._account, self._validation = account, validation
        if not validation.allowed:
            return ReadResult.failure(ACCOUNT_BLOCKED, *validation.reasons)
        return ReadResult(True, account)

    @property
    def account(self) -> MT5Account | None:
        return self._account

    # ---------------------------------------------------------------- symbols
    def get_symbols(self, *, refresh: bool = False) -> ReadResult:
        blocked = self._guard()
        if blocked is not None:
            return blocked
        if self._resolver is None or refresh:
            try:
                raw = self.module.symbols_get()
            except Exception:
                logger.exception("MT5 symbols_get failed")
                return ReadResult.failure("SYMBOLS_UNAVAILABLE")
            self._resolver = SymbolResolver(raw or (), self.canonical_symbols)
        return ReadResult(True, self._resolver.symbols)

    @property
    def resolver(self) -> SymbolResolver | None:
        return self._resolver

    def resolve_symbol(self, symbol: str) -> ReadResult:
        result = self.get_symbols()
        if not result.ok:
            return result
        try:
            return ReadResult(True, self._resolver.resolve(symbol))
        except SymbolResolutionError as error:
            return ReadResult(False, None, error.code, tuple(error.candidates) or (error.code,))

    def get_symbol_info(self, symbol: str) -> ReadResult:
        resolved = self.resolve_symbol(symbol)
        if not resolved.ok:
            return resolved
        info: SymbolInfo = resolved.data
        try:
            raw = self.module.symbol_info(info.name)
        except Exception:
            logger.exception("MT5 symbol_info failed")
            return ReadResult.failure("SYMBOL_INFO_UNAVAILABLE")
        if raw is None:
            return ReadResult.failure("SYMBOL_INFO_UNAVAILABLE")
        detail = SymbolResolver([raw], self.canonical_symbols).symbols[0]
        return ReadResult(True, {
            "symbol": info.canonical, "broker_symbol": detail.name,
            "description": detail.description, "digits": detail.digits, "point": detail.point,
            "spread": detail.spread, "visible": detail.visible, "path": detail.path,
            "source": "mt5",
        })

    # ------------------------------------------------------------ market data
    def get_tick(self, symbol: str) -> ReadResult:
        resolved = self.resolve_symbol(symbol)
        if not resolved.ok:
            return resolved
        info: SymbolInfo = resolved.data
        try:
            raw = self.module.symbol_info_tick(info.name)
        except Exception:
            logger.exception("MT5 symbol_info_tick failed")
            return ReadResult.failure("TICK_UNAVAILABLE")
        if raw is None:
            return ReadResult.failure("TICK_UNAVAILABLE")
        tick = self.reader.normalize_tick(raw, symbol=info.canonical)
        self._last_tick[info.canonical] = tick["timestamp"]
        return ReadResult(True, tick)

    def get_rates(self, symbol: str, timeframe: str, count: int | None = None) -> ReadResult:
        """Closed candles only, normalized onto the ALM candle schema."""
        resolved = self.resolve_symbol(symbol)
        if not resolved.ok:
            return resolved
        info: SymbolInfo = resolved.data
        name = str(timeframe).strip().upper()
        try:
            code = mt5_timeframe(name, self.module)
        except ValueError:
            return ReadResult.failure("UNSUPPORTED_TIMEFRAME", name)
        try:
            raw = self.module.copy_rates_from_pos(info.name, code, 0, int(count or self.default_count))
        except Exception:
            logger.exception("MT5 copy_rates_from_pos failed")
            return ReadResult.failure("RATES_UNAVAILABLE")
        if raw is None or len(raw) == 0:
            return ReadResult.failure("RATES_UNAVAILABLE")
        candles = self.reader.normalize_rates(raw, symbol=info.canonical, timeframe=name,
                                              as_of=self.now())
        if candles:
            self._last_candle[(info.canonical, name)] = candles[-1]["timestamp"]
        return ReadResult(True, candles)

    def get_multi_timeframe_rates(self, symbol: str, *, timeframes: Sequence[str] | None = None,
                                  count: int | None = None) -> dict[str, ReadResult]:
        """D1 through M5 in one call — Market Intelligence needs the whole ladder."""
        return {name: self.get_rates(symbol, name, count)
                for name in (timeframes or self.timeframes)}

    # ------------------------------------------------------------- positions
    def _canonical(self):
        """Ensure the resolver is loaded so broker names map to ALM names."""
        if self._resolver is None:
            self.get_symbols()
        return self._resolver.canonical_for if self._resolver else None

    def get_positions(self) -> ReadResult:
        blocked = self._guard()
        if blocked is not None:
            return blocked
        canonical = self._canonical()
        try:
            raw = self.module.positions_get()
        except Exception:
            logger.exception("MT5 positions_get failed")
            return ReadResult.failure("POSITIONS_UNAVAILABLE")
        positions: list[MT5Position] = self.positions_reader.read(raw or (), canonical=canonical)
        return ReadResult(True, positions)

    def get_orders(self) -> ReadResult:
        blocked = self._guard()
        if blocked is not None:
            return blocked
        canonical = self._canonical()
        try:
            raw = self.module.orders_get()
        except Exception:
            logger.exception("MT5 orders_get failed")
            return ReadResult.failure("ORDERS_UNAVAILABLE")
        orders: list[MT5Order] = self.history_reader.read_orders(raw or (), canonical=canonical)
        return ReadResult(True, orders)

    def get_history(self, *, start: datetime | None = None, end: datetime | None = None,
                    days: int = 7) -> ReadResult:
        blocked = self._guard()
        if blocked is not None:
            return blocked
        canonical = self._canonical()
        window_start, window_end = self.history_reader.default_window(days)
        start, end = start or window_start, end or window_end
        try:
            raw = self.module.history_deals_get(start, end)
        except Exception:
            logger.exception("MT5 history_deals_get failed")
            return ReadResult.failure("HISTORY_UNAVAILABLE")
        deals: list[MT5Deal] = self.history_reader.read_deals(raw or (), canonical=canonical)
        return ReadResult(True, deals)

    # ----------------------------------------------------------------- health
    def health_check(self, *, database_online: bool | None = None,
                     now: datetime | None = None) -> HealthReport:
        decision = self.safety.evaluate_data_access()
        terminal = self.connection.terminal_info()
        return self.health_monitor.check(
            terminal_available=terminal.available,
            connected=terminal.connected,
            account_valid=bool(self._validation and self._validation.allowed),
            server=self.settings.mt5_server or (self._account.server if self._account else None),
            database_online=database_online,
            ticks=dict(self._last_tick),
            candles=dict(self._last_candle),
            blocked=not decision.allowed,
            now=now or self.now(),
        )

    def identity(self) -> dict[str, Any]:
        """Dashboard identity block. Never contains a password or a raw login."""
        report = self.connection.last_report
        return {
            "broker": self.broker,
            "environment": self._account.environment if self._account else self.settings.environment,
            "server": (self._account.server if self._account else None) or self.settings.mt5_server,
            "login": self._account.masked_login if self._account else mask_login(self.settings.mt5_login),
            "trade_mode": str(self._validation.trade_mode) if self._validation else "UNKNOWN",
            "connection": "ONLINE" if self.is_connected() else "OFFLINE",
            "state": str(report.state) if report else str(ConnectionState.DISCONNECTED),
            "code": report.code if report else MT5_CREDENTIALS_MISSING,
            "read_only": True,
            "execution_enabled": False,
        }
