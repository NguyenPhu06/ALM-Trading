"""Phase 12 data-quality gate.

Wraps the shared MarketQualityValidator and adds the checks a live feed needs:
future timestamps, sufficient history, ordering, duplicates and freshness.

A failure means NO TRADE SIGNAL IS GENERATED. The gate returns the verdict; the
observation cycle stops on it rather than continuing with degraded data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Sequence

from data_quality.validator import timeframe_delta
from data_sources.validators import MarketQualityValidator, QualityStatus

FUTURE_TIMESTAMP = "FUTURE_TIMESTAMP"
DUPLICATE_CANDLE = "DUPLICATE_CANDLE"
BROKEN_OHLC = "BROKEN_OHLC"
NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
TIMEFRAME_MISALIGNED = "TIMEFRAME_MISALIGNED"
STALE_DATA = "STALE_DATA"
MISSING_CANDLES = "MISSING_CANDLES"
OUT_OF_ORDER = "OUT_OF_ORDER"
NO_DATA = "NO_DATA"
NAIVE_TIMESTAMP = "NAIVE_TIMESTAMP"

# Any of these means the batch cannot be analysed at all.
FATAL = frozenset({FUTURE_TIMESTAMP, DUPLICATE_CANDLE, BROKEN_OHLC, NON_POSITIVE_PRICE,
                   INSUFFICIENT_HISTORY, STALE_DATA, OUT_OF_ORDER, NO_DATA, NAIVE_TIMESTAMP})


class GateVerdict(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class GateResult:
    timeframe: str
    verdict: GateVerdict
    reasons: tuple[str, ...] = ()
    candles: int = 0
    latest: datetime | None = None
    age_seconds: float | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.verdict is not GateVerdict.FAIL

    @property
    def signal_allowed(self) -> bool:
        """A WARN still permits analysis; a FAIL never does."""
        return self.verdict is not GateVerdict.FAIL

    def as_dict(self) -> dict[str, Any]:
        return {"timeframe": self.timeframe, "verdict": str(self.verdict),
                "reasons": list(self.reasons), "candles": self.candles,
                "latest": self.latest, "age_seconds": self.age_seconds, **self.details}


class DataQualityGate:
    def __init__(self, *, minimum_candles: int = 60, freshness_multiplier: float = 3.0,
                 validator: MarketQualityValidator | None = None):
        self.minimum_candles = int(minimum_candles)
        self.freshness_multiplier = float(freshness_multiplier)
        self.validator = validator or MarketQualityValidator()

    def evaluate(self, candles: Sequence[dict[str, Any]], *, symbol: str, timeframe: str,
                 as_of: datetime | None = None) -> GateResult:
        now = as_of or datetime.now(timezone.utc)
        if not candles:
            return GateResult(timeframe, GateVerdict.FAIL, (NO_DATA,))

        reasons: list[str] = []
        delta = timeframe_delta(timeframe)
        step = int(delta.total_seconds())

        stamps: list[datetime] = []
        for candle in candles:
            stamp = candle.get("timestamp")
            if stamp is None:
                reasons.append(NO_DATA)
                continue
            if stamp.tzinfo is None:
                reasons.append(NAIVE_TIMESTAMP)
                stamp = stamp.replace(tzinfo=timezone.utc)
            stamps.append(stamp)
            # A closed candle's interval must have fully elapsed.
            if stamp + delta > now:
                reasons.append(FUTURE_TIMESTAMP)
            if step and int(stamp.timestamp()) % step != 0:
                reasons.append(TIMEFRAME_MISALIGNED)
            prices = [candle.get(name) for name in ("open", "high", "low", "close")]
            if any(price is None or float(price) <= 0 for price in prices):
                reasons.append(NON_POSITIVE_PRICE)
                continue
            high, low = float(candle["high"]), float(candle["low"])
            open_, close = float(candle["open"]), float(candle["close"])
            if not (low <= min(open_, close) and max(open_, close) <= high and low <= high):
                reasons.append(BROKEN_OHLC)

        if len(set(stamps)) != len(stamps):
            reasons.append(DUPLICATE_CANDLE)
        if stamps != sorted(stamps):
            reasons.append(OUT_OF_ORDER)
        if len(candles) < self.minimum_candles:
            reasons.append(INSUFFICIENT_HISTORY)

        latest = max(stamps) if stamps else None
        age = (now - latest).total_seconds() if latest else None
        if age is not None and age > delta.total_seconds() * self.freshness_multiplier:
            reasons.append(STALE_DATA)

        # Gaps are a warning: a real feed has weekend and holiday gaps.
        if len(stamps) > 1:
            expected = int((max(stamps) - min(stamps)).total_seconds() // step) + 1 if step else len(stamps)
            if expected - len(set(stamps)) > 0:
                reasons.append(MISSING_CANDLES)

        unique = tuple(dict.fromkeys(reasons))
        if FATAL & set(unique):
            # Stop here: the shared validator cannot sort a batch that mixes naive
            # and aware timestamps, and a fatal batch is discarded regardless.
            return GateResult(timeframe, GateVerdict.FAIL, unique, len(candles), latest,
                              round(age, 3) if age is not None else None, {"source": "mt5"})

        report = self.validator.evaluate(candles, symbol=symbol, timeframe=timeframe,
                                         as_of=now, source="mt5")
        if report.status is QualityStatus.INVALID:
            verdict = GateVerdict.FAIL
            unique = unique + tuple(report.reasons)
        else:
            verdict = GateVerdict.WARN if unique else GateVerdict.PASS
        return GateResult(timeframe, verdict, unique, len(candles), latest,
                          round(age, 3) if age is not None else None,
                          {"completeness": report.completeness, "source": "mt5"})

    def evaluate_all(self, batches: dict[str, Sequence[dict[str, Any]]], *, symbol: str,
                     as_of: datetime | None = None) -> dict[str, GateResult]:
        return {timeframe: self.evaluate(candles, symbol=symbol, timeframe=timeframe, as_of=as_of)
                for timeframe, candles in batches.items()}

    @staticmethod
    def signal_allowed(results: dict[str, GateResult]) -> bool:
        """Every timeframe must at least not FAIL before a signal may be produced."""
        return bool(results) and all(result.signal_allowed for result in results.values())
