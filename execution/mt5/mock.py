"""A fake MetaTrader5 module and a mock client, so unit tests need no terminal.

`FakeMT5Module` mimics the shapes the real package returns (namedtuple-like rows,
epoch seconds, integer trade modes) and is injected into the real `MT5Connection`
and `MT5ReadOnlyClient`. That means the tests exercise the production code paths
rather than a parallel implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from data_quality.validator import timeframe_delta
from execution.mt5.client import MT5ReadOnlyClient
from execution.mt5.connection import MT5Connection
from execution.mt5.market_data import MT5_TIMEFRAME_CODES

DEMO_TRADE_MODE = 0
CONTEST_TRADE_MODE = 1
REAL_TRADE_MODE = 2


class Row(dict):
    """Attribute access over a dict, like the MetaTrader5 namedtuple rows."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


@dataclass
class TerminalStub:
    connected: bool = True
    name: str = "MetaTrader 5"
    company: str = "Exness Technologies Ltd"
    path: str = r"C:\\Program Files\\MetaTrader 5 EXNESS"
    build: int = 4620
    trade_allowed: bool = True
    tradeapi_disabled: bool = False


def _rates(symbol: str, timeframe: str, count: int, *, now: datetime,
           base: float = 1.10, drift: float = 0.0002) -> list[Row]:
    delta = timeframe_delta(timeframe)
    # Real MT5 bars open on a timeframe boundary; anchor the series the same way.
    step = int(delta.total_seconds())
    anchor = int(now.timestamp()) // step * step
    rows = []
    for index in range(count):
        opened = datetime.fromtimestamp(anchor - step * (count - index), tz=timezone.utc)
        price = base + drift * index
        rows.append(Row(
            time=int(opened.timestamp()), open=price, high=price + 0.0006,
            low=price - 0.0004, close=price + 0.0003, tick_volume=120 + index,
            spread=12, real_volume=0,
        ))
    return rows


class FakeMT5Module:
    """Only the read functions exist. There is deliberately no order_send."""

    def __init__(self, *, trade_mode: int = DEMO_TRADE_MODE, connected: bool = True,
                 symbols: Sequence[str] = ("EURUSDm", "GBPUSDm", "XAUUSDm"),
                 server: str = "Exness-MT5Trial8", login: int = 987654321,
                 now: datetime | None = None, initialize_result: bool = True,
                 positions: Sequence[dict] | None = None, orders: Sequence[dict] | None = None,
                 deals: Sequence[dict] | None = None, tick_age_seconds: float = 0.5,
                 trade_allowed: bool = True, tradeapi_disabled: bool = False):
        self.trade_allowed = trade_allowed
        self.tradeapi_disabled = tradeapi_disabled
        self.trade_mode = trade_mode
        self.connected = connected
        self.symbol_names = tuple(symbols)
        self.server = server
        self.login = login
        self.now = now or datetime.now(timezone.utc)
        self.initialize_result = initialize_result
        self.initialized = False
        self.shutdown_called = False
        self.init_kwargs: dict[str, Any] = {}
        self._positions = list(positions or ())
        self._orders = list(orders or ())
        self._deals = list(deals or ())
        self.tick_age_seconds = tick_age_seconds
        for name in MT5_TIMEFRAME_CODES:
            setattr(self, f"TIMEFRAME_{name}", MT5_TIMEFRAME_CODES[name])

    # ------------------------------------------------------------- lifecycle
    def initialize(self, **kwargs: Any) -> bool:
        self.init_kwargs = dict(kwargs)
        self.initialized = bool(self.initialize_result)
        return self.initialized

    def shutdown(self) -> None:
        self.shutdown_called = True
        self.initialized = False

    def last_error(self) -> tuple[int, str]:
        return (-10005, "IPC timeout")

    def terminal_info(self) -> TerminalStub | None:
        if not self.initialized:
            return None
        return TerminalStub(connected=self.connected, trade_allowed=self.trade_allowed,
                            tradeapi_disabled=self.tradeapi_disabled)

    # --------------------------------------------------------------- reads
    def account_info(self) -> Row | None:
        if not self.initialized:
            return None
        return Row(login=self.login, server=self.server, currency="USD", balance=10000.0,
                   equity=10120.5, margin=250.0, margin_free=9870.5, margin_level=4048.2,
                   trade_mode=self.trade_mode, leverage=200, name="ALM Demo")

    def symbols_get(self) -> tuple[Row, ...]:
        return tuple(Row(name=name, description=f"{name} spot", digits=5, point=1e-05,
                         spread=12, visible=True, path=f"Forex\\{name}")
                     for name in self.symbol_names)

    def symbol_info(self, name: str) -> Row | None:
        for row in self.symbols_get():
            if row["name"] == name:
                return row
        return None

    def symbol_info_tick(self, name: str) -> Row | None:
        if name not in self.symbol_names:
            return None
        stamp = self.now - timedelta(seconds=self.tick_age_seconds)
        return Row(time=int(stamp.timestamp()), bid=1.10012, ask=1.10024, last=1.10018,
                   volume=7, time_msc=int(stamp.timestamp() * 1000), flags=6)

    def copy_rates_from_pos(self, name: str, timeframe: int, start: int, count: int):
        if name not in self.symbol_names:
            return None
        label = next((key for key, code in MT5_TIMEFRAME_CODES.items() if code == timeframe), "M15")
        return _rates(name, label, int(count), now=self.now)

    def positions_get(self):
        return tuple(Row(**row) for row in self._positions)

    def orders_get(self):
        return tuple(Row(**row) for row in self._orders)

    def history_deals_get(self, start: datetime, end: datetime):
        return tuple(Row(**row) for row in self._deals)


class FakeExecutionModule(FakeMT5Module):
    """FakeMT5Module plus order_send, for Phase 11 execution tests ONLY.

    The read-only FakeMT5Module deliberately has no order_send; this subclass is
    the explicit opt-in used to exercise MT5ExecutionClient. It records every
    payload so a test can assert exactly what would have been transmitted.
    """

    def __init__(self, *, retcode: int = 10009, fill_price: float = 1.10024,
                 ticket: int = 700001, fill_volume: float | None = None,
                 raise_on_send: bool = False, **kwargs: Any):
        super().__init__(**kwargs)
        self.retcode = retcode
        self.fill_price = fill_price
        self.ticket = ticket
        self.fill_volume = fill_volume
        self.raise_on_send = raise_on_send
        self.sent: list[dict[str, Any]] = []

    def order_send(self, payload: dict[str, Any]):
        self.sent.append(dict(payload))
        if self.raise_on_send:
            raise RuntimeError("transport failure")
        volume = self.fill_volume if self.fill_volume is not None else float(payload.get("volume", 0.0))
        # 10009 DONE and 10010 DONE_PARTIAL both fill; anything else is a refusal.
        if self.retcode not in (10009, 10010):
            return Row(retcode=self.retcode, volume=0.0, price=0.0, order=0,
                       comment="rejected by broker")
        self._positions.append({
            "ticket": self.ticket, "symbol": payload["symbol"],
            "type": payload["type"], "volume": volume,
            "price_open": self.fill_price, "price_current": self.fill_price,
            "sl": payload.get("sl", 0.0), "tp": payload.get("tp", 0.0),
            "profit": 0.0, "swap": 0.0, "commission": 0.0,
            "time": int(self.now.timestamp()),
            "magic": payload.get("magic", 0), "comment": payload.get("comment", ""),
        })
        return Row(retcode=self.retcode, volume=volume, price=self.fill_price,
                   order=self.ticket, deal=self.ticket, comment="Request executed")

    def positions_get(self, ticket: int | None = None):
        rows = tuple(Row(**row) for row in self._positions)
        if ticket is None:
            return rows
        return tuple(row for row in rows if row["ticket"] == int(ticket))


def demo_position(**overrides: Any) -> dict[str, Any]:
    row = {"ticket": 500001, "symbol": "EURUSDm", "type": 0, "volume": 0.10,
           "price_open": 1.09950, "price_current": 1.10012, "sl": 1.09500, "tp": 1.10500,
           "profit": 6.20, "swap": -0.15, "commission": -0.80,
           "time": int(datetime(2026, 8, 26, 8, tzinfo=timezone.utc).timestamp()),
           "magic": 0, "comment": "manual entry"}
    row.update(overrides)
    return row


class MockMT5ReadOnlyClient(MT5ReadOnlyClient):
    """MT5ReadOnlyClient wired to FakeMT5Module. Same code paths, no terminal.

    It inherits every read method and, like its parent, has no execution method.
    """

    def __init__(self, settings: Any = None, *, module: FakeMT5Module | None = None, **kwargs: Any):
        from config.settings import get_settings

        settings = settings or get_settings()
        fake = module or FakeMT5Module()
        connection = MT5Connection(settings, module=fake)
        kwargs.setdefault("now", fake.now)
        super().__init__(settings, connection=connection, **kwargs)
        self.fake = fake
