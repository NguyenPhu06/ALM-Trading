"""Data-quality gate for MT5 candles and ticks.

Reuses the shared `MarketQualityValidator` so MT5 is held to exactly the same
standard as every other provider, and adds the checks that are specific to a
broker feed: non-positive prices, timeframe misalignment and stale ticks.

Invalid data never reaches the strategy: `evaluate` returns INVALID and the
caller drops the batch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Sequence

from data_quality.validator import timeframe_delta
from data_sources.validators import DataQualityReport, MarketQualityValidator, QualityStatus

DATA_QUALITY_ERROR = "DATA_QUALITY_ERROR"
NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
TIMEFRAME_MISALIGNED = "TIMEFRAME_MISALIGNED"
DUPLICATE_TIMESTAMP = "DUPLICATE_TIMESTAMP"
UNKNOWN_SYMBOL = "UNKNOWN_SYMBOL"
STALE_TICK = "STALE_TICK"


@dataclass(frozen=True, slots=True)
class QualityOutcome:
    status: QualityStatus
    reasons: tuple[str, ...]
    report: DataQualityReport | None
    accepted: tuple[dict[str, Any], ...] = ()

    @property
    def valid(self) -> bool:
        return self.status is not QualityStatus.INVALID

    @property
    def code(self) -> str:
        return "OK" if self.valid else DATA_QUALITY_ERROR


class MT5DataQualityGate:
    def __init__(self, *, validator: MarketQualityValidator | None = None,
                 tick_stale_seconds: float = 30.0, known_symbols: Sequence[str] = ()):
        self.validator = validator or MarketQualityValidator()
        self.tick_stale_seconds = float(tick_stale_seconds)
        self.known_symbols = {str(item).upper() for item in known_symbols}

    def evaluate_candles(self, candles: Sequence[dict[str, Any]], *, symbol: str, timeframe: str,
                         as_of: datetime | None = None) -> QualityOutcome:
        now = as_of or datetime.now(timezone.utc)
        reasons: list[str] = []
        if self.known_symbols and symbol.upper() not in self.known_symbols:
            reasons.append(UNKNOWN_SYMBOL)

        report = self.validator.evaluate(candles, symbol=symbol, timeframe=timeframe,
                                         as_of=now, source="mt5")
        reasons.extend(report.reasons)

        delta = timeframe_delta(timeframe)
        seen: set[datetime] = set()
        for candle in candles:
            prices = [candle.get(name) for name in ("open", "high", "low", "close")]
            if any(price is None or float(price) <= 0 for price in prices):
                reasons.append(NON_POSITIVE_PRICE)
            stamp = candle["timestamp"]
            if stamp in seen:
                reasons.append(DUPLICATE_TIMESTAMP)
            seen.add(stamp)
            if int(stamp.timestamp()) % int(delta.total_seconds()) != 0:
                reasons.append(TIMEFRAME_MISALIGNED)

        unique = tuple(dict.fromkeys(reasons))
        fatal = {NON_POSITIVE_PRICE, DUPLICATE_TIMESTAMP, UNKNOWN_SYMBOL, "INVALID_OHLC", "NO_DATA"}
        status = (QualityStatus.INVALID if report.status is QualityStatus.INVALID
                  or fatal & set(unique) else
                  QualityStatus.WARNING if unique else QualityStatus.VALID)
        accepted = tuple(candles) if status is not QualityStatus.INVALID else ()
        return QualityOutcome(status, unique, report, accepted)

    def evaluate_tick(self, tick: dict[str, Any], *, as_of: datetime | None = None) -> QualityOutcome:
        now = as_of or datetime.now(timezone.utc)
        reasons: list[str] = []
        symbol = str(tick.get("symbol") or "")
        if self.known_symbols and symbol.upper() not in self.known_symbols:
            reasons.append(UNKNOWN_SYMBOL)
        for name in ("bid", "ask"):
            value = tick.get(name)
            if value is not None and float(value) <= 0:
                reasons.append(NON_POSITIVE_PRICE)
        stamp = tick.get("timestamp")
        if stamp is None:
            reasons.append("NO_TIMESTAMP")
        else:
            aware = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
            if (now - aware).total_seconds() > self.tick_stale_seconds:
                reasons.append(STALE_TICK)
        unique = tuple(dict.fromkeys(reasons))
        fatal = {NON_POSITIVE_PRICE, "NO_TIMESTAMP", UNKNOWN_SYMBOL}
        status = (QualityStatus.INVALID if fatal & set(unique) else
                  QualityStatus.WARNING if unique else QualityStatus.VALID)
        return QualityOutcome(status, unique, None, (tick,) if status is not QualityStatus.INVALID else ())


DATA_SOURCE_DISCREPANCY = "DATA_SOURCE_DISCREPANCY"


@dataclass(frozen=True, slots=True)
class SourceComparison:
    symbol: str
    mt5_price: float | None
    other_price: float | None
    price_difference: float | None
    spread_difference: float | None
    timestamp_difference: float | None
    discrepancy: bool
    reasons: tuple[str, ...]
    other_source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol, "mt5_price": self.mt5_price, "other_price": self.other_price,
            "price_difference": self.price_difference, "spread_difference": self.spread_difference,
            "timestamp_difference_seconds": self.timestamp_difference,
            "discrepancy": self.discrepancy, "reasons": list(self.reasons),
            "other_source": self.other_source, "code": DATA_SOURCE_DISCREPANCY if self.discrepancy else "OK",
        }


def compare_sources(mt5_quote: dict[str, Any] | None, other_quote: dict[str, Any] | None, *,
                    symbol: str, price_tolerance: float = 0.0010,
                    timestamp_tolerance_seconds: float = 120.0,
                    other_source: str = "provider") -> SourceComparison:
    """Warn only. Phase 10 never trades, so a discrepancy is recorded, not acted on."""
    def price(quote):
        if not quote:
            return None
        value = quote.get("mid_price") or quote.get("close")
        return float(value) if value is not None else None

    def spread(quote):
        value = (quote or {}).get("spread")
        return float(value) if value is not None else None

    mt5_price, other_price = price(mt5_quote), price(other_quote)
    reasons: list[str] = []
    if mt5_price is None or other_price is None:
        reasons.append("SOURCE_UNAVAILABLE")
        difference = None
    else:
        difference = abs(mt5_price - other_price)
        if difference > price_tolerance:
            reasons.append("PRICE_DIVERGENCE")

    mt5_spread, other_spread = spread(mt5_quote), spread(other_quote)
    spread_difference = (abs(mt5_spread - other_spread)
                         if mt5_spread is not None and other_spread is not None else None)

    stamps = [(quote or {}).get("timestamp") for quote in (mt5_quote, other_quote)]
    if all(stamps):
        aware = [stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc) for stamp in stamps]
        timestamp_difference = abs((aware[0] - aware[1]).total_seconds())
        if timestamp_difference > timestamp_tolerance_seconds:
            reasons.append("TIMESTAMP_DIVERGENCE")
    else:
        timestamp_difference = None

    divergent = any(reason in {"PRICE_DIVERGENCE", "TIMESTAMP_DIVERGENCE"} for reason in reasons)
    return SourceComparison(symbol, mt5_price, other_price, difference, spread_difference,
                            timestamp_difference, divergent, tuple(reasons), other_source)
