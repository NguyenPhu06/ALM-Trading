"""MT5 ticks and candles, normalized onto the ALM schema.

Everything leaving this module is a plain ALM dict produced by the shared
`CandleNormalizer`/`QuoteNormalizer`. No strategy code ever touches a MetaTrader5
object, a numpy record or a broker-specific symbol name.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from statistics import fmean
from typing import Any, Sequence

from data_quality.validator import timeframe_delta
from data_sources.normalizer import CandleNormalizer, QuoteNormalizer

MT5_SOURCE = "mt5"
SUPPORTED_TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")

# MetaTrader5 TIMEFRAME_* constants, kept as literals so the mapping is readable
# without the package installed. Resolved against the live module when present.
MT5_TIMEFRAME_CODES = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 16385, "H4": 16388, "D1": 16408, "W1": 32769, "MN1": 49153,
}


def mt5_timeframe(timeframe: str, module: Any | None = None) -> int:
    name = str(timeframe).strip().upper()
    if module is not None:
        attribute = getattr(module, f"TIMEFRAME_{name}", None)
        if attribute is not None:
            return int(attribute)
    if name not in MT5_TIMEFRAME_CODES:
        raise ValueError(f"unsupported MT5 timeframe: {timeframe}")
    return MT5_TIMEFRAME_CODES[name]


def _epoch_to_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def _read(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return getattr(row, name, default)


class SpreadState(StrEnum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    EXTREME = "EXTREME"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SpreadReading:
    symbol: str
    spread: float | None
    spread_percent: float | None
    average_spread: float | None
    ratio: float | None
    state: SpreadState

    @property
    def blocks_new_entry(self) -> bool:
        """Phase 10 records the state only; nothing trades from it yet."""
        return self.state is SpreadState.EXTREME


class SpreadMonitor:
    def __init__(self, *, window: int = 50, elevated_ratio: float = 1.5, extreme_ratio: float = 3.0):
        self.window = int(window)
        self.elevated_ratio = float(elevated_ratio)
        self.extreme_ratio = float(extreme_ratio)
        self._history: dict[str, list[float]] = {}

    def observe(self, symbol: str, spread: float | None, *, mid_price: float | None = None) -> SpreadReading:
        symbol = str(symbol).upper()
        if spread is None:
            return SpreadReading(symbol, None, None, None, None, SpreadState.UNKNOWN)
        spread = float(spread)
        history = self._history.setdefault(symbol, [])
        average = fmean(history) if history else None
        ratio = (spread / average) if average else None
        if ratio is None:
            state = SpreadState.NORMAL
        elif ratio >= self.extreme_ratio:
            state = SpreadState.EXTREME
        elif ratio >= self.elevated_ratio:
            state = SpreadState.ELEVATED
        else:
            state = SpreadState.NORMAL
        history.append(spread)
        del history[:-self.window]
        percent = (spread / mid_price) if mid_price else None
        return SpreadReading(symbol, spread, percent, average, ratio, state)

    def average(self, symbol: str) -> float | None:
        history = self._history.get(str(symbol).upper()) or []
        return fmean(history) if history else None


class MT5MarketDataReader:
    """Turns raw MT5 ticks/rates into normalized ALM records."""

    def __init__(self, *, candle_normalizer: CandleNormalizer | None = None,
                 quote_normalizer: QuoteNormalizer | None = None,
                 spread_monitor: SpreadMonitor | None = None):
        self.candles = candle_normalizer or CandleNormalizer()
        self.quotes = quote_normalizer or QuoteNormalizer()
        self.spread_monitor = spread_monitor or SpreadMonitor()

    def normalize_tick(self, raw: Any, *, symbol: str) -> dict[str, Any]:
        """`symbol` is the CANONICAL name, not the broker's decorated name."""
        bid = _read(raw, "bid")
        ask = _read(raw, "ask")
        quote = self.quotes.normalize({
            "timestamp": _epoch_to_utc(_read(raw, "time")),
            "symbol": symbol, "bid": bid, "ask": ask,
            "tick_volume": _read(raw, "volume"),
        }, source=MT5_SOURCE)
        mid = float(quote["mid_price"]) if quote.get("mid_price") is not None else None
        spread = float(quote["spread"]) if quote.get("spread") is not None else None
        reading = self.spread_monitor.observe(symbol, spread, mid_price=mid)
        last = _read(raw, "last")
        quote.update({
            "last": float(last) if last not in (None, "") else None,
            "spread_state": str(reading.state),
            "average_spread": reading.average_spread,
            "spread_ratio": reading.ratio,
            "provider": MT5_SOURCE,
        })
        return quote

    def normalize_rates(self, rows: Sequence[Any], *, symbol: str, timeframe: str,
                        as_of: datetime | None = None) -> list[dict[str, Any]]:
        """Closed candles only: a bar whose interval has not elapsed is dropped."""
        now = as_of or datetime.now(timezone.utc)
        delta = timeframe_delta(timeframe)
        candles: list[dict[str, Any]] = []
        for row in rows:
            opened = _epoch_to_utc(_read(row, "time"))
            if opened + delta > now:
                continue
            candles.append(self.candles.normalize({
                "timestamp": opened, "symbol": symbol, "timeframe": timeframe,
                "open": _read(row, "open"), "high": _read(row, "high"),
                "low": _read(row, "low"), "close": _read(row, "close"),
                "volume": _read(row, "real_volume") or _read(row, "tick_volume"),
                "tick_volume": _read(row, "tick_volume"),
                "spread": _read(row, "spread"),
                "is_closed": True, "provider": MT5_SOURCE, "provider_timestamp": opened,
            }, source=MT5_SOURCE))
        candles.sort(key=lambda candle: candle["timestamp"])
        return candles
