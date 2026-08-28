"""Turn a Phase 12 FeatureSnapshot into a flat, versioned feature vector.

Everything here is computable from information available AT the snapshot
timestamp. No field looks forward — that is the labeller's job, and it runs only
after the horizon has elapsed.

Feature names are stable and ordered. Adding or redefining one requires a new
FEATURE_VERSION (see versioning.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from ai.dataset.versioning import FEATURE_VERSION

TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5")
STRUCTURE_LABELS = ("HH", "HL", "LH", "LL")
SESSIONS = ("ASIA", "LONDON", "NEW_YORK", "LONDON_NEW_YORK_OVERLAP", "OFF_SESSION")
REGIMES = ("STRONG_BULL", "BULL", "RANGE", "BEAR", "STRONG_BEAR", "UNKNOWN")

# Named groups drive the explainability report (section 37).
FEATURE_GROUPS = {
    "market_structure": ("trend_", "structure_", "bos_", "choch_", "hh_", "hl_", "lh_", "ll_"),
    "liquidity": ("liquidity_", "sweep_", "displacement_", "rejection_", "distance_"),
    "ichimoku": ("ichimoku_",),
    "rsi": ("rsi_",),
    "adx": ("adx_",),
    "atr": ("atr_",),
    "session": ("session_", "hour_", "day_"),
    "mtf": ("regime_", "htf_", "ltf_", "conflict"),
    "spread_volatility": ("spread", "volatility_"),
    "strategy": ("strategy_", "dca_"),
}


def _direction(value: Any) -> float:
    text = str(value or "").upper()
    if any(token in text for token in ("BULL", "HH", "HL", "UP")):
        return 1.0
    if any(token in text for token in ("BEAR", "LH", "LL", "DOWN")):
        return -1.0
    return 0.0


def _number(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default          # drop NaN


@dataclass(frozen=True, slots=True)
class FeatureRow:
    timestamp: datetime
    symbol: str
    names: tuple[str, ...]
    values: tuple[float, ...]
    feature_version: str = FEATURE_VERSION
    context: dict[str, Any] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, float]:
        return dict(zip(self.names, self.values))

    @property
    def regime(self) -> str:
        return str(self.context.get("regime") or "UNKNOWN")

    @property
    def session(self) -> str:
        return str(self.context.get("session") or "OFF_SESSION")


class FeatureExtractor:
    """Builds a deterministic, ordered feature vector from a feature snapshot."""

    VERSION = FEATURE_VERSION

    def extract(self, snapshot: Mapping[str, Any]) -> FeatureRow:
        values: dict[str, float] = {}

        structure = snapshot.get("structure") or {}
        indicators = snapshot.get("indicators") or {}
        volatility = snapshot.get("volatility") or {}

        # ---- per-timeframe structure and indicators -------------------------
        for timeframe in TIMEFRAMES:
            state = structure.get(timeframe) or {}
            prefix = timeframe.lower()
            values[f"trend_{prefix}"] = _direction(state.get("trend"))
            values[f"structure_{prefix}"] = _direction(state.get("structure"))
            values[f"bos_{prefix}"] = _direction(state.get("bos"))
            values[f"choch_{prefix}"] = _direction(state.get("choch"))
            for label in STRUCTURE_LABELS:
                values[f"{label.lower()}_{prefix}"] = float(
                    str(state.get("structure") or "").upper() == label)

            frame = indicators.get(timeframe) or {}
            values[f"rsi_{prefix}"] = _number(frame.get("rsi"), 50.0)
            values[f"adx_{prefix}"] = _number(frame.get("adx"))
            values[f"atr_{prefix}"] = _number(frame.get("atr"))
            tenkan = _number(frame.get("ichimoku_tenkan"))
            kijun = _number(frame.get("ichimoku_kijun"))
            values[f"ichimoku_tenkan_{prefix}"] = tenkan
            values[f"ichimoku_kijun_{prefix}"] = kijun
            values[f"ichimoku_cross_{prefix}"] = tenkan - kijun
            values[f"ichimoku_above_cloud_{prefix}"] = float(bool(frame.get("price_above_cloud")))
            values[f"ichimoku_below_cloud_{prefix}"] = float(bool(frame.get("price_below_cloud")))
            values[f"volatility_{prefix}"] = _number((volatility.get(timeframe) or {}).get("value"))

        # ---- liquidity ------------------------------------------------------
        liquidity = snapshot.get("liquidity") or {}
        observed = liquidity.get("observed") or []
        inferred = liquidity.get("inferred") or []
        values["liquidity_observed_count"] = float(len(observed))
        values["liquidity_inferred_count"] = float(len(inferred))
        kinds = [str(item.get("event_type") or "").upper() for item in observed]
        values["sweep_present"] = float(any("SWEEP" in kind for kind in kinds))
        values["displacement_present"] = float(any("DISPLACEMENT" in kind for kind in kinds))
        values["rejection_present"] = float(any("REJECTION" in kind for kind in kinds))
        values["liquidity_pool_present"] = float(bool(inferred))

        # ---- distance to reference levels ----------------------------------
        price = _number((snapshot.get("market_data") or {}).get("mid_price"))
        values["price"] = price
        levels = self._reference_levels(snapshot)
        for name, level in levels.items():
            values[f"distance_{name}"] = (price - level) if level and price else 0.0

        # ---- spread and volatility -----------------------------------------
        spread = snapshot.get("spread") or {}
        values["spread"] = _number(spread.get("spread"))
        values["spread_percent"] = _number(spread.get("spread_percent"))
        values["spread_elevated"] = float(str(spread.get("state") or "").upper() == "ELEVATED")
        values["spread_extreme"] = float(str(spread.get("state") or "").upper() == "EXTREME")

        # ---- regime ---------------------------------------------------------
        regime = snapshot.get("regime") or {}
        regime_name = str(regime.get("regime") or "UNKNOWN").upper()
        for candidate in REGIMES:
            values[f"regime_{candidate.lower()}"] = float(regime_name == candidate)
        values["htf_score"] = _number(regime.get("htf_score"))
        values["ltf_score"] = _number(regime.get("ltf_score"))
        values["regime_conflict"] = float(bool(regime.get("conflict")))

        # ---- session and clock ---------------------------------------------
        session_block = snapshot.get("session") or {}
        session_name = str(session_block.get("session") or "OFF_SESSION").upper()
        for candidate in SESSIONS:
            values[f"session_{candidate.lower()}"] = float(session_name == candidate)
        timestamp = self._timestamp(snapshot)
        values["hour_of_day"] = float(timestamp.hour) if timestamp else 0.0
        values["day_of_week"] = float(timestamp.weekday()) if timestamp else 0.0

        # ---- strategy and DCA state ----------------------------------------
        strategy = snapshot.get("strategy") or {}
        values["strategy_score"] = _number(strategy.get("score"))
        values["strategy_confidence"] = _number(strategy.get("confidence"))
        values["strategy_executable"] = float(
            str(strategy.get("status") or "").upper() == "EXECUTABLE_SIMULATION")
        values["strategy_direction"] = _direction(strategy.get("direction"))
        dca = snapshot.get("dca_projection") or {}
        values["dca_levels_planned"] = _number(dca.get("levels_planned"))
        values["dca_total_volume"] = _number(dca.get("total_volume"))

        names = tuple(sorted(values))
        return FeatureRow(
            timestamp=timestamp, symbol=str(snapshot.get("symbol") or ""),
            names=names, values=tuple(values[name] for name in names),
            feature_version=self.VERSION,
            context={"regime": regime_name, "session": session_name,
                     "cycle_id": snapshot.get("cycle_id"),
                     "price": price, "spread": values["spread"]},
        )

    @staticmethod
    def _reference_levels(snapshot: Mapping[str, Any]) -> dict[str, float]:
        """Previous-day and session extremes, plus nearest support/resistance."""
        levels: dict[str, float] = {}
        structure = snapshot.get("structure") or {}
        daily = structure.get("D1") or {}
        levels["previous_day_high"] = _number(daily.get("swing_high"))
        levels["previous_day_low"] = _number(daily.get("swing_low"))
        intraday = structure.get("M15") or {}
        levels["session_high"] = _number(intraday.get("swing_high"))
        levels["session_low"] = _number(intraday.get("swing_low"))
        hourly = structure.get("H1") or {}
        levels["resistance"] = _number(hourly.get("swing_high"))
        levels["support"] = _number(hourly.get("swing_low"))
        return levels

    @staticmethod
    def _timestamp(snapshot: Mapping[str, Any]) -> datetime | None:
        value = snapshot.get("timestamp")
        if isinstance(value, datetime):
            return value
        if isinstance(value, str) and value:
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                return None
        return None

    @classmethod
    def group_for(cls, name: str) -> str:
        for group, prefixes in FEATURE_GROUPS.items():
            if any(name.startswith(prefix) or name == prefix.rstrip("_") for prefix in prefixes):
                return group
        return "other"

    @classmethod
    def grouped(cls, names: Sequence[str]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for name in names:
            groups.setdefault(cls.group_for(name), []).append(name)
        return groups
