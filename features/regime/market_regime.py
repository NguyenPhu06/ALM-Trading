from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Mapping, Sequence

from features.indicators import IndicatorSnapshot
from features.liquidity import LiquidityEventData
from features.structure import StructureEventData


class StructuralTrend(StrEnum):
    STRONGLY_BULLISH = "STRONGLY_BULLISH"
    BULLISH = "BULLISH"
    NEUTRAL = "NEUTRAL"
    BEARISH = "BEARISH"
    STRONGLY_BEARISH = "STRONGLY_BEARISH"


class MarketState(StrEnum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    TREND_RETRACEMENT = "TREND_RETRACEMENT"
    COUNTER_TREND = "COUNTER_TREND"
    POSSIBLE_REVERSAL = "POSSIBLE_REVERSAL"
    CONFIRMED_REVERSAL = "CONFIRMED_REVERSAL"
    RANGE = "RANGE"
    TRANSITION = "TRANSITION"
    UNCERTAIN = "UNCERTAIN"


class ReversalConfidence(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlignmentLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class TimeframeRegime:
    timeframe: str
    role: str
    available: bool
    trend: StructuralTrend
    strength: float
    structure_state: str
    hh: int = 0
    hl: int = 0
    lh: int = 0
    ll: int = 0
    last_bos: str | None = None
    last_choch: str | None = None
    swing_high: Decimal | None = None
    swing_low: Decimal | None = None
    liquidity_high: Decimal | None = None
    liquidity_low: Decimal | None = None
    equal_high: Decimal | None = None
    equal_low: Decimal | None = None
    previous_high: Decimal | None = None
    previous_low: Decimal | None = None
    session_high: Decimal | None = None
    session_low: Decimal | None = None
    missing_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MultiTimeframeTrendSnapshot:
    as_of: datetime
    symbol: str
    timeframes: dict[str, TimeframeRegime]
    missing_timeframes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LiquidityMapEntry:
    timeframe: str
    price: Decimal
    type: str
    strength: float
    distance_from_price: Decimal
    swept: bool
    sweep_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class InstitutionalFlowInput:
    cot_score: float | None = None
    bank_participation_score: float | None = None
    cme_volume_score: float | None = None
    cme_open_interest_score: float | None = None


@dataclass(frozen=True, slots=True)
class MarketRegimeSnapshot:
    symbol: str
    as_of: datetime
    trend_matrix: MultiTimeframeTrendSnapshot
    htf_bias: StructuralTrend
    ltf_direction: StructuralTrend
    market_state: MarketState
    reversal_confidence: ReversalConfidence
    timeframe_alignment: AlignmentLevel
    htf_structure_score: float
    institutional_flow_score: float | None
    institutional_bias: str
    liquidity_map: tuple[LiquidityMapEntry, ...]
    indicator_snapshot: dict[str, IndicatorSnapshot]
    structure_conflicts: tuple[str, ...] = field(default_factory=tuple)
    indicator_conflicts: tuple[str, ...] = field(default_factory=tuple)
    institutional_conflicts: tuple[str, ...] = field(default_factory=tuple)
    signal: None = None


class MarketRegimeEngine:
    TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")
    ROLES = {
        "D1": "MACRO_REGIME", "H4": "PRIMARY_STRUCTURAL_TREND",
        "H1": "TRADING_DIRECTION_CONFIRMATION", "M15": "LIQUIDITY_SETUP",
        "M5": "ENTRY_REFINEMENT", "M1": "EXECUTION_TIMING",
    }

    def __init__(
        self,
        *,
        structure_weights: Mapping[str, float] | None = None,
        ltf_weights: Mapping[str, float] | None = None,
    ):
        self.structure_weights = dict(structure_weights or {"D1": 0.40, "H4": 0.30, "H1": 0.20, "M15": 0.10})
        self.ltf_weights = dict(ltf_weights or {"M15": 0.60, "M5": 0.25, "M1": 0.15})
        if abs(sum(self.structure_weights.values()) - 1.0) > 1e-9:
            raise ValueError("structure weights must sum to 1.0")
        if abs(sum(self.ltf_weights.values()) - 1.0) > 1e-9:
            raise ValueError("LTF weights must sum to 1.0")

    def calculate(
        self,
        *,
        symbol: str,
        as_of: datetime,
        available_timeframes: Sequence[str],
        structure_events: Mapping[str, Sequence[StructureEventData]],
        liquidity_events: Mapping[str, Sequence[LiquidityEventData]],
        indicators: Mapping[str, IndicatorSnapshot],
        current_price: Decimal,
        institutional: InstitutionalFlowInput | None = None,
    ) -> MarketRegimeSnapshot:
        available = set(available_timeframes)
        states = {
            timeframe: self._timeframe_state(
                timeframe, available=timeframe in available,
                structure_events=structure_events.get(timeframe, ()),
                liquidity_events=liquidity_events.get(timeframe, ()),
                as_of=as_of,
            )
            for timeframe in self.TIMEFRAMES
        }
        trend_matrix = MultiTimeframeTrendSnapshot(
            as_of, symbol, states, tuple(tf for tf in self.TIMEFRAMES if tf not in available),
        )
        htf_bias = self._group_trend(states, {"D1": 0.45, "H4": 0.35, "H1": 0.20})
        ltf_direction = self._group_trend(states, self.ltf_weights)
        htf_score = round(sum(
            self._signed_strength(states[timeframe]) * weight
            for timeframe, weight in self.structure_weights.items()
        ) * 100.0, 2)
        liquidity_map = self._liquidity_map(liquidity_events, current_price, as_of)
        market_state = self._market_state(states, htf_bias, ltf_direction)
        reversal = self._reversal_confidence(states, structure_events, liquidity_events, htf_bias, ltf_direction, as_of)
        alignment = self._alignment(states, htf_bias, ltf_direction)
        institutional_score, institutional_bias = self._institutional(institutional)
        structure_conflicts = self._structure_conflicts(states, htf_bias, ltf_direction)
        indicator_conflicts = self._indicator_conflicts(states, indicators)
        institutional_conflicts = self._institutional_conflicts(htf_bias, ltf_direction, institutional_score)
        return MarketRegimeSnapshot(
            symbol, as_of, trend_matrix, htf_bias, ltf_direction, market_state,
            reversal, alignment, htf_score, institutional_score, institutional_bias,
            liquidity_map, dict(indicators), structure_conflicts, indicator_conflicts,
            institutional_conflicts,
        )

    def _timeframe_state(
        self, timeframe: str, *, available: bool,
        structure_events: Sequence[StructureEventData],
        liquidity_events: Sequence[LiquidityEventData], as_of: datetime,
    ) -> TimeframeRegime:
        if not available:
            return TimeframeRegime(
                timeframe, self.ROLES[timeframe], False, StructuralTrend.NEUTRAL,
                0.0, "MISSING", missing_reason="NO_CLOSED_CANDLES",
            )
        structure = [event for event in structure_events if self._confirmed_at(event, as_of)]
        liquidity = [event for event in liquidity_events if self._confirmed_at(event, as_of)]
        counts = {kind: sum(event.event_type == kind for event in structure) for kind in ("HH", "HL", "LH", "LL")}
        bull_bos = sum(event.event_type == "BULLISH_BOS" for event in structure)
        bear_bos = sum(event.event_type == "BEARISH_BOS" for event in structure)
        bull_score = min(1.0, counts["HH"] * 0.15 + counts["HL"] * 0.15 + bull_bos * 0.35)
        bear_score = min(1.0, counts["LH"] * 0.15 + counts["LL"] * 0.15 + bear_bos * 0.35)
        bull_sequence = counts["HH"] > 0 and counts["HL"] > 0 and bull_bos > 0
        bear_sequence = counts["LH"] > 0 and counts["LL"] > 0 and bear_bos > 0
        if bull_sequence and not bear_sequence:
            trend = StructuralTrend.STRONGLY_BULLISH if bull_score >= 0.85 else StructuralTrend.BULLISH
            strength, state = bull_score, "BULLISH_SEQUENCE"
        elif bear_sequence and not bull_sequence:
            trend = StructuralTrend.STRONGLY_BEARISH if bear_score >= 0.85 else StructuralTrend.BEARISH
            strength, state = bear_score, "BEARISH_SEQUENCE"
        elif bull_sequence and bear_sequence:
            difference = bull_score - bear_score
            if difference >= 0.35:
                trend, strength, state = StructuralTrend.BULLISH, difference, "BULLISH_TRANSITION"
            elif difference <= -0.35:
                trend, strength, state = StructuralTrend.BEARISH, abs(difference), "BEARISH_TRANSITION"
            else:
                trend, strength, state = StructuralTrend.NEUTRAL, 1.0 - abs(difference), "MIXED_TRANSITION"
        else:
            trend, strength, state = StructuralTrend.NEUTRAL, max(bull_score, bear_score), "INSUFFICIENT_STRUCTURAL_SEQUENCE"
        last = lambda suffix: next((event.direction for event in reversed(structure) if event.event_type.endswith(suffix)), None)
        structure_price = lambda kind: next((event.price for event in reversed(structure) if event.event_type == kind), None)
        level_price = lambda *types: next((event.price for event in reversed(liquidity) if event.metadata.get("level_type") in types), None)
        highs = [event.price for event in liquidity if event.event_type == "LIQUIDITY_LEVEL" and event.direction == "HIGH"]
        lows = [event.price for event in liquidity if event.event_type == "LIQUIDITY_LEVEL" and event.direction == "LOW"]
        return TimeframeRegime(
            timeframe, self.ROLES[timeframe], True, trend, round(strength, 4), state,
            counts["HH"], counts["HL"], counts["LH"], counts["LL"],
            last("BOS"), last("CHOCH"), structure_price("SWING_HIGH"), structure_price("SWING_LOW"),
            max(highs) if highs else None, min(lows) if lows else None,
            level_price("EQUAL_HIGH"), level_price("EQUAL_LOW"),
            level_price("PREVIOUS_DAY_HIGH", "PREVIOUS_WEEK_HIGH", "PREVIOUS_MONTH_HIGH"),
            level_price("PREVIOUS_DAY_LOW", "PREVIOUS_WEEK_LOW", "PREVIOUS_MONTH_LOW"),
            level_price("CURRENT_SESSION_HIGH", "PREVIOUS_SESSION_HIGH"),
            level_price("CURRENT_SESSION_LOW", "PREVIOUS_SESSION_LOW"),
        )

    @staticmethod
    def _confirmed_at(event: object, as_of: datetime) -> bool:
        timestamp = getattr(event, "event_timestamp")
        confirmation = getattr(event, "confirmation_timestamp", None)
        return timestamp <= as_of and (confirmation is None or confirmation <= as_of)

    @staticmethod
    def _direction(trend: StructuralTrend) -> int:
        if trend in {StructuralTrend.BULLISH, StructuralTrend.STRONGLY_BULLISH}:
            return 1
        if trend in {StructuralTrend.BEARISH, StructuralTrend.STRONGLY_BEARISH}:
            return -1
        return 0

    @classmethod
    def _signed_strength(cls, state: TimeframeRegime) -> float:
        return cls._direction(state.trend) * state.strength if state.available else 0.0

    @classmethod
    def _group_trend(cls, states: Mapping[str, TimeframeRegime], weights: Mapping[str, float]) -> StructuralTrend:
        score = sum(cls._signed_strength(states[timeframe]) * weight for timeframe, weight in weights.items())
        if score >= 0.65:
            return StructuralTrend.STRONGLY_BULLISH
        if score >= 0.20:
            return StructuralTrend.BULLISH
        if score <= -0.65:
            return StructuralTrend.STRONGLY_BEARISH
        if score <= -0.20:
            return StructuralTrend.BEARISH
        return StructuralTrend.NEUTRAL

    def _market_state(
        self, states: Mapping[str, TimeframeRegime],
        htf: StructuralTrend, ltf: StructuralTrend,
    ) -> MarketState:
        htf_direction, ltf_direction = self._direction(htf), self._direction(ltf)
        any_events = any(state.hh + state.hl + state.lh + state.ll for state in states.values())
        d1_direction = self._direction(states["D1"].trend)
        h4_direction = self._direction(states["H4"].trend)
        h1_direction = self._direction(states["H1"].trend)
        if d1_direction and ltf_direction == -d1_direction and h4_direction == h1_direction == ltf_direction:
            return MarketState.CONFIRMED_REVERSAL
        if d1_direction and h4_direction == d1_direction and h1_direction == ltf_direction == -d1_direction:
            return MarketState.POSSIBLE_REVERSAL
        if htf_direction == 0:
            return MarketState.TRANSITION if any(self._direction(states[tf].trend) for tf in ("D1", "H4", "H1")) else MarketState.RANGE if any_events else MarketState.UNCERTAIN
        if ltf_direction == 0:
            return MarketState.TRANSITION
        if htf_direction == ltf_direction:
            return MarketState.TREND_CONTINUATION
        if h1_direction == ltf_direction and h4_direction == ltf_direction:
            return MarketState.CONFIRMED_REVERSAL
        if h1_direction == ltf_direction:
            return MarketState.POSSIBLE_REVERSAL
        return MarketState.TREND_RETRACEMENT

    def _reversal_confidence(
        self, states: Mapping[str, TimeframeRegime],
        structure: Mapping[str, Sequence[StructureEventData]],
        liquidity: Mapping[str, Sequence[LiquidityEventData]],
        htf: StructuralTrend, ltf: StructuralTrend, as_of: datetime,
    ) -> ReversalConfidence:
        reference_direction = self._direction(htf) or self._direction(states["D1"].trend)
        if reference_direction == 0 or self._direction(ltf) in {0, reference_direction}:
            return ReversalConfidence.LOW
        direction = "BULLISH" if self._direction(ltf) > 0 else "BEARISH"
        sweep = any(
            event.event_type == "LIQUIDITY_SWEEP" and event.direction == direction and self._confirmed_at(event, as_of)
            for tf in ("M15", "M5", "M1") for event in liquidity.get(tf, ())
        )
        choch = any(
            event.event_type == f"{direction}_CHOCH" and self._confirmed_at(event, as_of)
            for tf in ("M15", "M5", "M1") for event in structure.get(tf, ())
        )
        m15 = self._direction(states["M15"].trend) == self._direction(ltf)
        h1 = self._direction(states["H1"].trend) == self._direction(ltf)
        h4 = self._direction(states["H4"].trend) == self._direction(ltf)
        if sweep and choch and m15 and h1 and h4:
            return ReversalConfidence.HIGH
        if sweep and choch and m15 and h1:
            return ReversalConfidence.MEDIUM
        return ReversalConfidence.LOW

    def _alignment(self, states: Mapping[str, TimeframeRegime], htf: StructuralTrend, ltf: StructuralTrend) -> AlignmentLevel:
        available = [state for state in states.values() if state.available and self._direction(state.trend)]
        if not available:
            return AlignmentLevel.UNAVAILABLE
        target = self._direction(htf) or self._direction(ltf)
        ratio = sum(self._direction(state.trend) == target for state in available) / len(available)
        return AlignmentLevel.HIGH if ratio >= 0.8 else AlignmentLevel.MEDIUM if ratio >= (2 / 3) else AlignmentLevel.LOW

    @staticmethod
    def _institutional(value: InstitutionalFlowInput | None) -> tuple[float | None, str]:
        if value is None:
            return None, "UNAVAILABLE"
        scores = [score for score in (
            value.cot_score, value.bank_participation_score,
            value.cme_volume_score, value.cme_open_interest_score,
        ) if score is not None]
        if not scores:
            return None, "UNAVAILABLE"
        score = round(max(-100.0, min(100.0, sum(scores) / len(scores))), 2)
        bias = "BULLISH" if score >= 20 else "BEARISH" if score <= -20 else "NEUTRAL"
        return score, bias

    @staticmethod
    def _liquidity_map(
        events: Mapping[str, Sequence[LiquidityEventData]], current_price: Decimal, as_of: datetime,
    ) -> tuple[LiquidityMapEntry, ...]:
        result = []
        for timeframe, rows in events.items():
            visible = [row for row in rows if MarketRegimeEngine._confirmed_at(row, as_of)]
            sweeps = [row for row in visible if row.event_type == "LIQUIDITY_SWEEP"]
            for level in (row for row in visible if row.event_type == "LIQUIDITY_LEVEL"):
                matching = next((
                    sweep for sweep in reversed(sweeps)
                    if sweep.metadata.get("level_type") == level.metadata.get("level_type")
                    and sweep.metadata.get("liquidity_level") == str(level.price)
                    and sweep.event_timestamp >= level.event_timestamp
                ), None)
                result.append(LiquidityMapEntry(
                    timeframe, level.price, str(level.metadata.get("level_type", "UNKNOWN")),
                    float(level.strength or 0), abs(level.price - current_price),
                    matching is not None, matching.event_timestamp if matching else None,
                ))
        return tuple(sorted(result, key=lambda item: item.distance_from_price))

    def _structure_conflicts(self, states: Mapping[str, TimeframeRegime], htf: StructuralTrend, ltf: StructuralTrend) -> tuple[str, ...]:
        conflicts = []
        if self._direction(htf) and self._direction(ltf) == -self._direction(htf):
            conflicts.append(f"HTF_{htf.value}_VS_LTF_{ltf.value}")
        for timeframe in ("D1", "H4", "H1"):
            if self._direction(states[timeframe].trend) and self._direction(states[timeframe].trend) != self._direction(htf):
                conflicts.append(f"{timeframe}_CONFLICTS_WITH_HTF_BIAS")
        return tuple(conflicts)

    def _indicator_conflicts(
        self, states: Mapping[str, TimeframeRegime], indicators: Mapping[str, IndicatorSnapshot],
    ) -> tuple[str, ...]:
        conflicts = []
        for timeframe, indicator in indicators.items():
            if indicator.rsi is None:
                continue
            direction = self._direction(states[timeframe].trend)
            if direction < 0 and indicator.rsi >= 70:
                conflicts.append(f"{timeframe}_BEARISH_STRUCTURE_RSI_OVERBOUGHT")
            elif direction > 0 and indicator.rsi <= 30:
                conflicts.append(f"{timeframe}_BULLISH_STRUCTURE_RSI_OVERSOLD")
        return tuple(conflicts)

    def _institutional_conflicts(
        self, htf: StructuralTrend, ltf: StructuralTrend, score: float | None,
    ) -> tuple[str, ...]:
        if score is None:
            return ("INSTITUTIONAL_DATA_UNAVAILABLE",)
        institutional_direction = 1 if score >= 20 else -1 if score <= -20 else 0
        conflicts = []
        if institutional_direction and self._direction(htf) and institutional_direction != self._direction(htf):
            conflicts.append("INSTITUTIONAL_HTF_CONFLICT")
        if institutional_direction and self._direction(ltf) and institutional_direction != self._direction(ltf):
            conflicts.append("INSTITUTIONAL_LTF_CONFLICT")
        return tuple(conflicts)
