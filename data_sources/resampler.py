from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

from data_quality.validator import timeframe_delta


class MarketDataResampler:
    CONVERSIONS = {
        ("M1", "M5"): 5,
        ("M5", "M15"): 3,
        ("M15", "M30"): 2,
        ("M15", "H1"): 4,
        ("H1", "H4"): 4,
        ("H4", "D1"): 6,
    }
    METHOD = "UTC_COMPLETE_BUCKET_OHLCV_V1"

    @staticmethod
    def _value(candle: Any, name: str, default: Any = None) -> Any:
        return candle.get(name, default) if isinstance(candle, dict) else getattr(candle, name, default)

    @staticmethod
    def _aware(timestamp: datetime) -> datetime:
        aware = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
        return aware.astimezone(timezone.utc)

    @classmethod
    def _bucket_start(cls, timestamp: datetime, target: str) -> datetime:
        timestamp = cls._aware(timestamp)
        if target == "D1":
            return timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        if target == "H4":
            return timestamp.replace(hour=(timestamp.hour // 4) * 4, minute=0, second=0, microsecond=0)
        if target == "H1":
            return timestamp.replace(minute=0, second=0, microsecond=0)
        minutes = 30 if target == "M30" else 15 if target == "M15" else 5
        return timestamp.replace(minute=(timestamp.minute // minutes) * minutes, second=0, microsecond=0)

    def resample(
        self, candles: Sequence[Any], source_timeframe: str, target_timeframe: str,
        *, as_of: datetime | None = None,
    ) -> list[dict[str, Any]]:
        conversion = (source_timeframe, target_timeframe)
        if conversion not in self.CONVERSIONS:
            raise ValueError(f"unsupported resampling conversion: {source_timeframe}->{target_timeframe}")
        as_of = self._aware(as_of) if as_of else None
        expected = self.CONVERSIONS[conversion]
        source_delta = timeframe_delta(source_timeframe)
        target_delta = timeframe_delta(target_timeframe)
        groups: dict[datetime, list[Any]] = {}
        for candle in sorted(candles, key=lambda row: self._value(row, "timestamp")):
            if self._value(candle, "timeframe") != source_timeframe:
                raise ValueError("source candle timeframe mismatch")
            if self._value(candle, "is_closed", True) is not True:
                continue
            close_time = self._aware(self._value(candle, "timestamp")) + source_delta
            if as_of and close_time > as_of:
                continue
            bucket = self._bucket_start(self._value(candle, "timestamp"), target_timeframe)
            groups.setdefault(bucket, []).append(candle)

        output = []
        for open_time, rows in sorted(groups.items()):
            rows.sort(key=lambda row: self._value(row, "timestamp"))
            actual = [self._aware(self._value(row, "timestamp")) for row in rows]
            required = [open_time + source_delta * index for index in range(expected)]
            close_time = open_time + target_delta
            if len(rows) != expected or actual != required or (as_of and close_time > as_of):
                continue
            volumes = [self._value(row, "volume") for row in rows if self._value(row, "volume") is not None]
            tick_volumes = [self._value(row, "tick_volume") for row in rows if self._value(row, "tick_volume") is not None]
            source = str(self._value(rows[0], "source"))
            output.append({
                "timestamp": open_time,
                "symbol": str(self._value(rows[0], "symbol")),
                "timeframe": target_timeframe,
                "open": Decimal(str(self._value(rows[0], "open"))),
                "high": max(Decimal(str(self._value(row, "high"))) for row in rows),
                "low": min(Decimal(str(self._value(row, "low"))) for row in rows),
                "close": Decimal(str(self._value(rows[-1], "close"))),
                "volume": sum((Decimal(str(value)) for value in volumes), Decimal("0")) if volumes else None,
                "tick_volume": sum((Decimal(str(value)) for value in tick_volumes), Decimal("0")) if tick_volumes else None,
                "spread": self._value(rows[-1], "spread"),
                "is_closed": True,
                "source": f"{source}:resampled:{target_timeframe}",
                "provider": str(self._value(rows[0], "provider", source)),
                "provider_timestamp": close_time,
                "source_timeframe": source_timeframe,
                "target_timeframe": target_timeframe,
                "resampling_method": self.METHOD,
            })
        return output
