from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from data_quality.validator import timeframe_delta
from features.candles import candle_close_time, candle_is_closed, candle_value


@dataclass(frozen=True, slots=True)
class AggregatedCandle:
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    is_closed: bool = True
    source: str = "phase_1b_resample"

    @property
    def timestamp(self) -> datetime:
        return self.open_time


class MTFResampler:
    SOURCE_TIMEFRAME = "M15"
    TARGETS = {"H1": 4, "H4": 16, "D1": 96}

    @staticmethod
    def _aware(timestamp: datetime) -> datetime:
        return timestamp if timestamp.tzinfo is not None and timestamp.utcoffset() is not None else timestamp.replace(tzinfo=timezone.utc)

    @classmethod
    def _bucket_start(cls, timestamp: datetime, timeframe: str) -> datetime:
        timestamp = cls._aware(timestamp).astimezone(timezone.utc)
        if timeframe == "D1":
            return timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        hours = 1 if timeframe == "H1" else 4
        return timestamp.replace(hour=(timestamp.hour // hours) * hours, minute=0, second=0, microsecond=0)

    def resample(
        self,
        candles: Sequence[Any],
        timeframe: str,
        *,
        as_of: datetime | None = None,
    ) -> list[AggregatedCandle]:
        if timeframe not in self.TARGETS:
            raise ValueError(f"unsupported resample target: {timeframe}")
        if as_of is not None:
            as_of = self._aware(as_of)
        groups: dict[datetime, list[Any]] = {}
        for candle in sorted(candles, key=lambda item: candle_value(item, "timestamp")):
            if str(candle_value(candle, "timeframe")) != self.SOURCE_TIMEFRAME:
                raise ValueError("MTF resampling requires M15 source candles")
            if not candle_is_closed(candle):
                continue
            if as_of is not None and self._aware(candle_close_time(candle)) > as_of:
                continue
            start = self._bucket_start(candle_value(candle, "timestamp"), timeframe)
            groups.setdefault(start, []).append(candle)

        result: list[AggregatedCandle] = []
        expected_count = self.TARGETS[timeframe]
        target_delta = timeframe_delta(timeframe)
        source_delta = timeframe_delta(self.SOURCE_TIMEFRAME)
        for open_time, rows in sorted(groups.items()):
            rows.sort(key=lambda item: candle_value(item, "timestamp"))
            expected_times = [open_time + source_delta * index for index in range(expected_count)]
            actual_times = [self._aware(candle_value(row, "timestamp")) for row in rows]
            close_time = open_time + target_delta
            complete = len(rows) == expected_count and actual_times == expected_times
            if not complete or (as_of is not None and close_time > as_of):
                continue
            volumes = [candle_value(row, "volume") for row in rows if candle_value(row, "volume") is not None]
            result.append(AggregatedCandle(
                symbol=str(candle_value(rows[0], "symbol")), timeframe=timeframe,
                open_time=open_time, close_time=close_time,
                open=Decimal(str(candle_value(rows[0], "open"))),
                high=max(Decimal(str(candle_value(row, "high"))) for row in rows),
                low=min(Decimal(str(candle_value(row, "low"))) for row in rows),
                close=Decimal(str(candle_value(rows[-1], "close"))),
                volume=sum((Decimal(str(value)) for value in volumes), Decimal("0")) if volumes else None,
            ))
        return result
