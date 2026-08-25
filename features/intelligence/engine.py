from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping, Sequence

from config.settings import load_yaml
from features.candles import candle_close_time, candle_value, closed_candle_prefix, utc_aware
from features.indicators import MTFIndicatorEngine
from features.intelligence.models import (
    ConfluenceScore, FeatureVector, MarketBias, MarketStateSnapshot, TimeframeIntelligence,
)
from features.liquidity import LiquidityEngine
from features.session import SessionEngine, SessionName
from features.smc import DisplacementDetector, FairValueGapDetector, OrderBlockDetector
from features.structure import MarketStructureEngine
from features.volatility import VolatilityEngine


class MarketIntelligenceEngine:
    TIMEFRAMES = ("D1", "H4", "H1", "M30", "M15", "M5", "M1")
    DEFAULT_WEIGHTS = {"D1": 0.30, "H4": 0.24, "H1": 0.18, "M30": 0.10, "M15": 0.08, "M5": 0.06, "M1": 0.04}
    TREND_VALUE = {"BULLISH": 1.0, "BEARISH": -1.0, "RANGING": 0.0, "UNKNOWN": 0.0}

    def __init__(self):
        config = load_yaml()
        phase = config.get("phase_3", {})
        sessions = config.get("sessions", {})
        weights = phase.get("timeframe_weights", self.DEFAULT_WEIGHTS)
        self.weights = {timeframe: float(weights.get(timeframe, self.DEFAULT_WEIGHTS[timeframe])) for timeframe in self.TIMEFRAMES}
        if abs(sum(self.weights.values()) - 1.0) > 1e-9:
            raise ValueError("Phase 3 timeframe weights must sum to 1.0")
        self.structure = MarketStructureEngine(
            swing_left_bars=int(phase.get("swing_left_bars", 2)),
            swing_right_bars=int(phase.get("swing_right_bars", 2)),
            minimum_swing_distance=int(phase.get("minimum_swing_distance", 1)),
            minimum_swing_price_move=phase.get("minimum_swing_price_move", 0),
            break_mode=phase.get("break_mode", "CLOSE_BREAK"),
            equal_level_tolerance_points=float(phase.get("equal_level_tolerance_points", 3)),
            point_size=phase.get("point_size", 0.00001),
        )
        self.internal_structure = MarketStructureEngine(
            swing_left_bars=1, swing_right_bars=1,
            break_mode=phase.get("break_mode", "CLOSE_BREAK"),
            equal_level_tolerance_points=float(phase.get("equal_level_tolerance_points", 3)),
            point_size=phase.get("point_size", 0.00001),
        )
        self.session = SessionEngine(
            timezone=sessions.get("timezone", "UTC"), asia=tuple(sessions.get("asia", ("00:00", "09:00"))),
            london=tuple(sessions.get("london", ("07:00", "16:00"))),
            new_york=tuple(sessions.get("new_york", ("13:00", "22:00"))),
        )
        self.liquidity = LiquidityEngine(
            swing_left_bars=int(phase.get("swing_left_bars", 2)),
            swing_right_bars=int(phase.get("swing_right_bars", 2)),
            equal_level_tolerance_points=float(phase.get("equal_level_tolerance_points", 3)),
            point_size=phase.get("point_size", 0.00001),
            minimum_rejection_ratio=float(phase.get("minimum_rejection_ratio", 0.15)),
            session_engine=self.session,
        )
        self.indicators = MTFIndicatorEngine(
            rsi_period=int(phase.get("rsi_period", 14)), adx_period=int(phase.get("adx_period", 14)),
            atr_period=int(phase.get("atr_period", 14)), tenkan_period=int(phase.get("tenkan_period", 9)),
            kijun_period=int(phase.get("kijun_period", 26)), senkou_b_period=int(phase.get("senkou_b_period", 52)),
        )
        self.fvg = FairValueGapDetector(minimum_size=phase.get("minimum_fvg_size", 0))
        self.order_blocks = OrderBlockDetector(
            lookback=int(phase.get("order_block_lookback", 5)),
            atr_period=int(phase.get("atr_period", 14)),
            minimum_atr_ratio=float(phase.get("displacement_atr_ratio", 1.5)),
        )
        self.displacement = DisplacementDetector(
            atr_period=int(phase.get("atr_period", 14)),
            minimum_atr_ratio=float(phase.get("displacement_atr_ratio", 1.5)),
            minimum_body_ratio=float(phase.get("displacement_body_ratio", 0.6)),
        )
        self.volatility = VolatilityEngine(
            atr_period=int(phase.get("atr_period", 14)), rolling_period=int(phase.get("volatility_period", 20)),
        )
        self.abnormal_spread_ratio = float(phase.get("abnormal_spread_ratio", 0.001))

    def calculate(
        self, symbol: str, candles_by_timeframe: Mapping[str, Sequence[Any]], *, as_of: datetime,
    ) -> MarketStateSnapshot:
        as_of = utc_aware(as_of)
        states = {
            timeframe: self._timeframe(symbol.upper(), timeframe, candles_by_timeframe.get(timeframe, ()), as_of)
            for timeframe in self.TIMEFRAMES
        }
        return self.aggregate(symbol.upper(), states, as_of=as_of)

    def aggregate(
        self, symbol: str, states: Mapping[str, TimeframeIntelligence], *, as_of: datetime,
    ) -> MarketStateSnapshot:
        bias, bias_score = self._bias(states)
        confluence = self._confluence(states, bias, bias_score)
        confluence = ConfluenceScore(
            confluence.score, confluence.components, confluence.reasons, confluence.conflicts,
            timestamp=utc_aware(as_of), symbol=symbol.upper(),
        )
        no_trade = self._no_trade(states, bias)
        vector = self._feature_vector(states)
        vector = FeatureVector(
            vector.names, vector.values, timestamp=utc_aware(as_of), symbol=symbol.upper(),
        )
        reasons = confluence.reasons
        conflicts = tuple(dict.fromkeys((*confluence.conflicts, *no_trade)))
        regime = self._mtf_regime(states)
        return MarketStateSnapshot(
            utc_aware(as_of), symbol.upper(), dict(states), bias, bias_score, confluence,
            "NO_TRADE" if no_trade else "OBSERVE", tuple(no_trade), reasons, conflicts, vector,
            market_regime=regime, mtf_alignment=regime["alignment"],
            confidence=regime["confidence"], data_quality=self._data_quality(states, utc_aware(as_of)),
        )

    def _timeframe(
        self, symbol: str, timeframe: str, candles: Sequence[Any], as_of: datetime,
    ) -> TimeframeIntelligence:
        visible = [row for row in closed_candle_prefix(candles) if candle_close_time(row) <= as_of]
        if not visible:
            indicator = self.indicators.calculate((), timeframe, as_of=as_of)
            return TimeframeIntelligence(
                None, symbol, timeframe, False, "UNKNOWN", None, None, None, None, None,
                {}, None, None, None, None, asdict(indicator), {}, None, None,
            )
        structure = self.structure.calculate(visible)
        internal = self.internal_structure.calculate(visible)
        liquidity = self.liquidity.calculate(visible)
        liquidity_map = self.liquidity.map_from_events(liquidity)
        swings_high = [event for event in structure if event.event_type == "SWING_HIGH"]
        swings_low = [event for event in structure if event.event_type == "SWING_LOW"]
        bos = next((event.direction for event in reversed(structure) if event.event_type.endswith("BOS")), None)
        choch = next((event.direction for event in reversed(structure) if event.event_type.endswith("CHOCH")), None)
        latest_structure = next((event.event_type for event in reversed(structure) if event.event_type in {"HH", "HL", "LH", "LL"}), None)
        latest_internal = next((event.event_type for event in reversed(internal) if event.event_type in {"HH", "HL", "LH", "LL"}), None)
        equal_highs = tuple(float(event.price) for event in structure if event.event_type == "EQUAL_HIGH")
        equal_lows = tuple(float(event.price) for event in structure if event.event_type == "EQUAL_LOW")
        levels = [event for event in liquidity if event.event_type == "LIQUIDITY_LEVEL"]
        price = Decimal(str(candle_value(visible[-1], "close")))
        highs = [event for event in levels if event.price > price]
        lows = [event for event in levels if event.price < price]
        sweep = next((event for event in reversed(liquidity) if event.event_type == "LIQUIDITY_SWEEP"), None)
        fvgs = self.fvg.detect(visible)
        blocks = self.order_blocks.detect(visible)
        displacements = self.displacement.detect(visible)
        indicator = self.indicators.calculate(visible, timeframe, as_of=as_of)
        indicator_data = asdict(indicator)
        indicator_data["close"] = float(price)
        spread = candle_value(visible[-1], "spread", None)
        indicator_data["spread"] = float(spread) if spread is not None else None
        volatility = self.volatility.calculate(visible)
        stats = self.session.statistics(visible)
        latest_stats = stats[-1] if stats else None
        latest_displacement = next((item for item in reversed(displacements) if item.displaced), None)
        swing_high = float(swings_high[-1].price) if swings_high else None
        swing_low = float(swings_low[-1].price) if swings_low else None
        equilibrium = (swing_high + swing_low) / 2 if swing_high is not None and swing_low is not None else None
        premium_discount = "PREMIUM" if equilibrium is not None and float(price) > equilibrium else "DISCOUNT" if equilibrium is not None and float(price) < equilibrium else "EQUILIBRIUM" if equilibrium is not None else None
        trend = self.structure.trend_state(structure).value
        regime = self._timeframe_regime(trend, choch, indicator_data.get("trend_direction"))
        last = visible[-1]
        return TimeframeIntelligence(
            candle_close_time(visible[-1]), symbol, timeframe, True,
            trend, latest_structure, bos, choch, swing_high, swing_low,
            {
                "nearest_buy_side": float(min(highs, key=lambda item: item.price).price) if highs else None,
                "nearest_sell_side": float(max(lows, key=lambda item: item.price).price) if lows else None,
                "level_count": len(levels),
                "levels": [asdict(item) for item in liquidity_map[-20:]],
            },
            asdict(sweep) if sweep else None,
            asdict(fvgs[-1]) if fvgs else None,
            asdict(blocks[-1]) if blocks else None,
            asdict(latest_displacement) if latest_displacement else None,
            indicator_data, asdict(volatility) if volatility else {},
            self.session.session_for(candle_value(visible[-1], "timestamp")).value,
            latest_stats.range if latest_stats else None,
            ohlcv={name: float(candle_value(last, name)) if candle_value(last, name) is not None else None for name in ("open", "high", "low", "close", "volume")},
            candle_closed=True, internal_structure=latest_internal,
            swing_structure=latest_structure, equal_highs=equal_highs, equal_lows=equal_lows,
            premium_discount=premium_discount, regime=regime,
        )

    def _bias(self, states: Mapping[str, TimeframeIntelligence]) -> tuple[MarketBias, float]:
        score = 0.0
        available_weight = 0.0
        for timeframe, state in states.items():
            if not state.available:
                continue
            weight = self.weights[timeframe]
            available_weight += weight
            structural = self.TREND_VALUE[state.trend]
            event = 0.2 if state.bos == "BULLISH" or state.choch == "BULLISH" else -0.2 if state.bos == "BEARISH" or state.choch == "BEARISH" else 0.0
            score += weight * max(-1.0, min(1.0, structural * 0.8 + event))
        normalized = score / available_weight if available_weight else 0.0
        bias = (
            MarketBias.STRONG_BULLISH if normalized >= 0.60 else
            MarketBias.BULLISH if normalized >= 0.20 else
            MarketBias.STRONG_BEARISH if normalized <= -0.60 else
            MarketBias.BEARISH if normalized <= -0.20 else MarketBias.NEUTRAL
        )
        return bias, round(normalized * 100.0, 2)

    @staticmethod
    def _timeframe_regime(trend: str, choch: str | None, indicator_direction: str | None) -> str:
        if choch:
            return "TRANSITIONAL"
        if trend in {"BULLISH", "BEARISH"} and indicator_direction in {"BULLISH", "BEARISH"} and trend != indicator_direction:
            return "CONFLICTING"
        return trend

    def _mtf_regime(self, states: Mapping[str, TimeframeIntelligence]) -> dict[str, Any]:
        def group(timeframes: tuple[str, ...]) -> str:
            score = sum(self.TREND_VALUE[states[timeframe].trend] for timeframe in timeframes if states[timeframe].available)
            return "BULLISH" if score > 0 else "BEARISH" if score < 0 else "RANGING"

        htf_frames, ltf_frames = ("D1", "H4", "H1"), ("M30", "M15", "M5")
        higher, lower = group(htf_frames), group(ltf_frames)
        available_required = sum(states[timeframe].available for timeframe in (*htf_frames, *ltf_frames))
        coverage = available_required / 6.0
        htf_trends = [states[timeframe].trend for timeframe in htf_frames if states[timeframe].available and states[timeframe].trend in {"BULLISH", "BEARISH"}]
        if not htf_trends:
            htf_agreement = 0.0
        else:
            htf_agreement = max(htf_trends.count("BULLISH"), htf_trends.count("BEARISH")) / len(htf_trends)
        if higher in {"BULLISH", "BEARISH"} and lower == higher:
            alignment, alignment_score = "ALIGNED", 1.0
        elif higher in {"BULLISH", "BEARISH"} and lower in {"BULLISH", "BEARISH"}:
            alignment, alignment_score = "COUNTER_TREND", 0.6
        elif available_required < 3:
            alignment, alignment_score = "INSUFFICIENT", 0.0
        else:
            alignment, alignment_score = "MIXED", 0.3
        d1, h4 = states["D1"], states["H4"]
        htf_conflict = d1.trend in {"BULLISH", "BEARISH"} and h4.trend in {"BULLISH", "BEARISH"} and d1.trend != h4.trend
        transitional = any(states[timeframe].regime == "TRANSITIONAL" for timeframe in (*htf_frames, *ltf_frames))
        if htf_conflict:
            state = "CONFLICTING"
        elif transitional or alignment == "COUNTER_TREND":
            state = "TRANSITIONAL"
        elif higher == "RANGING":
            state = "RANGING"
        else:
            state = higher
        confidence = round(100.0 * (0.4 * coverage + 0.4 * htf_agreement + 0.2 * alignment_score), 2)
        return {
            "state": state, "higher_timeframe_bias": higher,
            "lower_timeframe_state": lower, "alignment": alignment,
            "confidence": confidence,
        }

    @staticmethod
    def _data_quality(states: Mapping[str, TimeframeIntelligence], as_of: datetime) -> dict[str, Any]:
        available = [timeframe for timeframe, state in states.items() if state.available]
        missing = [timeframe for timeframe, state in states.items() if not state.available]
        insufficient = [
            timeframe for timeframe, state in states.items()
            if state.available and state.indicators.get("missing_reason") == "INSUFFICIENT_HISTORY"
        ]
        timestamps = [state.timestamp for state in states.values() if state.timestamp is not None]
        return {
            "available_timeframes": available, "missing_timeframes": missing,
            "insufficient_indicator_history": insufficient,
            "latest_feature_timestamp": max(timestamps) if timestamps else None,
            "as_of": as_of, "all_candles_closed": all(state.candle_closed is not False for state in states.values()),
            "news_risk_available": False,
        }

    def _confluence(
        self, states: Mapping[str, TimeframeIntelligence], bias: MarketBias, bias_score: float,
    ) -> ConfluenceScore:
        bullish = bias in {MarketBias.BULLISH, MarketBias.STRONG_BULLISH}
        bearish = bias in {MarketBias.BEARISH, MarketBias.STRONG_BEARISH}
        reasons, conflicts = [], []
        components = {"hierarchical_structure": round(abs(bias_score) / 20.0, 2)}
        for timeframe, state in states.items():
            if not state.available:
                continue
            aligned = (bullish and state.trend == "BULLISH") or (bearish and state.trend == "BEARISH")
            if aligned:
                reasons.append(f"{timeframe} {state.trend.lower()} structure")
            elif state.trend in {"BULLISH", "BEARISH"} and (bullish or bearish):
                conflicts.append(f"{timeframe} {state.trend.lower()} structure conflicts with hierarchical bias")
            if state.bos:
                reasons.append(f"{timeframe} BOS {state.bos.lower()}")
            if state.sweep:
                reasons.append(f"{timeframe} {state.sweep['metadata'].get('liquidity_side', '').lower()} liquidity sweep")
        h1 = states["H1"]
        if h1.indicators.get("trend_strength") in {"MODERATE_TREND", "STRONG_TREND"}:
            reasons.append(f"H1 ADX indicates {h1.indicators['trend_strength'].lower()}")
            components["trend_confirmation"] = 1.0
        score = max(0.0, min(10.0, 5.0 + abs(bias_score) / 20.0 + components.get("trend_confirmation", 0.0) - len(conflicts) * 0.75))
        return ConfluenceScore(round(score, 2), components, tuple(reasons), tuple(conflicts))

    def _no_trade(self, states: Mapping[str, TimeframeIntelligence], bias: MarketBias) -> list[str]:
        reasons = []
        if sum(state.available for state in states.values()) < 3:
            reasons.append("INSUFFICIENT_DATA")
        d1, h4 = states["D1"], states["H4"]
        if d1.trend in {"BULLISH", "BEARISH"} and h4.trend in {"BULLISH", "BEARISH"} and d1.trend != h4.trend:
            reasons.append("CONFLICTING_HIGHER_TIMEFRAMES")
        if any(state.volatility.get("state") == "EXTREME_VOLATILITY" for state in states.values() if state.available):
            reasons.append("EXTREME_VOLATILITY")
        if bias is MarketBias.NEUTRAL:
            reasons.append("UNCLEAR_STRUCTURE")
        available = [state for state in states.values() if state.available]
        if available and not any(state.liquidity.get("level_count", 0) for state in available):
            reasons.append("LOW_LIQUIDITY_CONTEXT")
        if available and all(state.session == SessionName.OFF_SESSION.value for state in available[-3:]):
            reasons.append("SESSION_UNSUITABLE")
        for state in available:
            spread = state.indicators.get("spread")
            if spread is not None and state.indicators.get("close") and spread / state.indicators["close"] > self.abnormal_spread_ratio:
                reasons.append("ABNORMAL_SPREAD")
                break
        if not any(state.bos or state.choch or state.sweep or state.displacement for state in available):
            reasons.append("NO_CONFIRMATION")
        return list(dict.fromkeys(reasons))

    def _feature_vector(self, states: Mapping[str, TimeframeIntelligence]) -> FeatureVector:
        names, values = [], []
        encode_trend = {"BEARISH": -1.0, "RANGING": 0.0, "UNKNOWN": 0.0, "BULLISH": 1.0}
        for timeframe in self.TIMEFRAMES:
            names.append(f"trend_{timeframe.lower()}")
            values.append(encode_trend[states[timeframe].trend])
        for indicator in ("rsi", "adx"):
            for timeframe in ("D1", "H4", "H1", "M30", "M15", "M5"):
                names.append(f"{indicator}_{timeframe.lower()}")
                values.append(float(states[timeframe].indicators.get(indicator) or 0.0))
        for timeframe in ("H1", "M15", "M5"):
            names.append(f"atr_{timeframe.lower()}")
            values.append(float(states[timeframe].indicators.get("atr") or 0.0))
        m15 = states["M15"]
        close = float(m15.indicators.get("close") or 0.0)
        liquidity_prices = [value for value in (
            m15.liquidity.get("nearest_buy_side"), m15.liquidity.get("nearest_sell_side"),
        ) if value is not None]
        liquidity_distance = min((abs(float(value) - close) for value in liquidity_prices), default=0.0)
        nearest_type = 0.0
        if liquidity_prices and close:
            nearest = min(liquidity_prices, key=lambda value: abs(float(value) - close))
            nearest_type = 1.0 if nearest == m15.liquidity.get("nearest_buy_side") else -1.0
        sweep_direction = 1.0 if m15.sweep and m15.sweep.get("direction") == "BULLISH" else -1.0 if m15.sweep and m15.sweep.get("direction") == "BEARISH" else 0.0
        fvg_mid = (float(m15.fvg["upper_price"]) + float(m15.fvg["lower_price"])) / 2 if m15.fvg else close
        block_mid = (float(m15.order_block["zone_high"]) + float(m15.order_block["zone_low"])) / 2 if m15.order_block else close
        premium_map = {None: 0.0, "DISCOUNT": -1.0, "EQUILIBRIUM": 0.0, "PREMIUM": 1.0}
        structure_map = {None: 0.0, "LL": -2.0, "LH": -1.0, "HL": 1.0, "HH": 2.0}
        direction_map = {None: 0.0, "BEARISH": -1.0, "BULLISH": 1.0}
        ichimoku_state = 1.0 if m15.indicators.get("price_above_cloud") else -1.0 if m15.indicators.get("price_below_cloud") else 0.0
        names.extend((
            "liquidity_distance", "nearest_liquidity_type", "sweep_direction",
            "fvg_distance", "order_block_distance", "premium_discount",
            "ichimoku_state", "structure_state", "bos", "choch", "spread", "news_risk",
        ))
        values.extend((
            liquidity_distance, nearest_type, sweep_direction, abs(fvg_mid - close), abs(block_mid - close),
            premium_map[m15.premium_discount], ichimoku_state, structure_map.get(m15.structure, 0.0),
            direction_map.get(m15.bos, 0.0), direction_map.get(m15.choch, 0.0),
            float(m15.indicators.get("spread") or 0.0), 0.0,
        ))
        session_map = {name.value: float(index) for index, name in enumerate(SessionName)}
        volatility_map = {None: 0.0, "LOW_VOLATILITY": 1.0, "NORMAL_VOLATILITY": 2.0, "HIGH_VOLATILITY": 3.0, "EXTREME_VOLATILITY": 4.0}
        names.extend(("session", "volatility_state"))
        values.extend((session_map.get(states["M15"].session, 0.0), volatility_map.get(states["M15"].volatility.get("state"), 0.0)))
        return FeatureVector(tuple(names), tuple(values))
