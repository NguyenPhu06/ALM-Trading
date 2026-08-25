from __future__ import annotations

from datetime import datetime
from typing import Any

from features.intelligence import MarketStateSnapshot


class HistoricalFeatureSchema:
    """Stable numeric Phase 4 schema extracted only from a causal snapshot at T."""

    VERSION = "phase4.features.v1"
    TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")
    TREND = {"BEARISH": -1.0, "RANGING": 0.0, "UNKNOWN": 0.0, "BULLISH": 1.0}
    STRUCTURE = {None: 0.0, "LL": -2.0, "LH": -1.0, "HL": 1.0, "HH": 2.0}
    DIRECTION = {None: 0.0, "BEARISH": -1.0, "BULLISH": 1.0}
    VOLATILITY = {None: 0.0, "LOW_VOLATILITY": 1.0, "NORMAL_VOLATILITY": 2.0, "HIGH_VOLATILITY": 3.0, "EXTREME_VOLATILITY": 4.0}
    SESSION = {"OFF_SESSION": 0.0, "ASIA": 1.0, "LONDON": 2.0, "NEW_YORK": 3.0, "OVERLAP": 4.0}
    LIQUIDITY = {None: 0.0, "PREVIOUS_DAY_HIGH": 1.0, "PREVIOUS_DAY_LOW": -1.0,
                 "CONFIRMED_SWING_HIGH": 2.0, "CONFIRMED_SWING_LOW": -2.0,
                 "EQUAL_HIGH": 3.0, "EQUAL_LOW": -3.0}

    @classmethod
    def extract(cls, snapshot: MarketStateSnapshot) -> dict[str, float]:
        features: dict[str, float] = {}
        for timeframe in cls.TIMEFRAMES:
            state = snapshot.timeframes[timeframe]
            prefix = timeframe.lower()
            features[f"{prefix}_available"] = float(state.available)
            features[f"{prefix}_trend"] = cls.TREND.get(state.trend, 0.0)
            features[f"{prefix}_structure"] = cls.STRUCTURE.get(state.swing_structure, 0.0)
            features[f"{prefix}_atr"] = cls._number(state.indicators.get("atr"))
            features[f"{prefix}_adx"] = cls._number(state.indicators.get("adx"))
            features[f"{prefix}_rsi"] = cls._number(state.indicators.get("rsi"))
            if timeframe in {"D1", "H4", "H1"}:
                features[f"{prefix}_ichimoku_state"] = (
                    1.0 if state.indicators.get("price_above_cloud") else
                    -1.0 if state.indicators.get("price_below_cloud") else 0.0
                )

        m15 = snapshot.timeframes["M15"]
        close = cls._number(m15.indicators.get("close"))
        levels = list(m15.liquidity.get("levels", ()))
        features["distance_to_previous_day_high"] = cls._level_distance(levels, "PREVIOUS_DAY_HIGH", close)
        features["distance_to_previous_day_low"] = cls._level_distance(levels, "PREVIOUS_DAY_LOW", close)
        features["distance_to_swing_high"] = cls._price_distance(m15.swing_high, close)
        features["distance_to_swing_low"] = cls._price_distance(m15.swing_low, close)
        nearest_type = cls._nearest_type(levels, close)
        features["nearest_liquidity_type"] = cls.LIQUIDITY.get(nearest_type, 0.0)
        features["liquidity_sweep"] = cls.DIRECTION.get(m15.sweep.get("direction") if m15.sweep else None, 0.0)
        features["bos"] = cls.DIRECTION.get(m15.bos, 0.0)
        features["choch"] = cls.DIRECTION.get(m15.choch, 0.0)
        for kind in ("HH", "HL", "LH", "LL"):
            features[kind.lower()] = float(m15.swing_structure == kind)
        features["atr_percent"] = cls._number(m15.volatility.get("atr_percentage"))
        features["volatility_regime"] = cls.VOLATILITY.get(m15.volatility.get("state"), 0.0)
        features["session"] = cls.SESSION.get(m15.session or "OFF_SESSION", 0.0)
        timestamp = cls._timestamp(snapshot.timestamp)
        features["day_of_week"] = float(timestamp.weekday())
        features["hour"] = float(timestamp.hour)
        features["minute"] = float(timestamp.minute)
        features["is_even_hour"] = float(timestamp.hour % 2 == 0)
        return features

    @staticmethod
    def _number(value: Any) -> float:
        return float(value) if value is not None else 0.0

    @staticmethod
    def _timestamp(value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("feature timestamp must be timezone-aware")
        return value

    @classmethod
    def _level_distance(cls, levels: list[dict[str, Any]], level_type: str, close: float) -> float:
        candidates = [cls._number(level.get("price")) for level in levels if level.get("type") == level_type and not level.get("swept")]
        return min((abs(price - close) for price in candidates), default=0.0)

    @staticmethod
    def _price_distance(price: float | None, close: float) -> float:
        return abs(float(price) - close) if price is not None and close else 0.0

    @classmethod
    def _nearest_type(cls, levels: list[dict[str, Any]], close: float) -> str | None:
        active = [level for level in levels if not level.get("swept") and level.get("price") is not None]
        return min(active, key=lambda level: abs(cls._number(level["price"]) - close)).get("type") if active else None
