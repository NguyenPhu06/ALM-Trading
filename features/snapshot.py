from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Sequence

from features.candles import candle_close_time, candle_is_closed
from features.liquidity import LiquidityEventData
from features.session import SessionEngine
from features.structure import MarketStructureEngine, StructureEventData

if TYPE_CHECKING:
    from features.mtf import MTFAlignment


def create_feature_snapshot(
    candle: Any,
    structure_events: Sequence[StructureEventData],
    liquidity_events: Sequence[LiquidityEventData],
    *,
    session_engine: SessionEngine | None = None,
    mtf_alignment: "MTFAlignment | None" = None,
) -> dict[str, Any]:
    value = lambda name: candle[name] if isinstance(candle, dict) else getattr(candle, name)
    timestamp: datetime = value("timestamp")
    if not candle_is_closed(candle):
        raise ValueError("feature snapshots require a closed candle")
    as_of = candle_close_time(candle)
    price = Decimal(str(value("close")))
    visible_structure = [event for event in structure_events if event.event_timestamp <= as_of and (event.confirmation_timestamp is None or event.confirmation_timestamp <= as_of)]
    visible_liquidity = [event for event in liquidity_events if event.event_timestamp <= as_of and (event.confirmation_timestamp is None or event.confirmation_timestamp <= as_of)]
    bias, _ = MarketStructureEngine.bias(visible_structure)
    last_bos = next((event.direction for event in reversed(visible_structure) if event.event_type.endswith("BOS")), None)
    last_choch = next((event.direction for event in reversed(visible_structure) if event.event_type.endswith("CHOCH")), None)
    levels = [event for event in visible_liquidity if event.event_type == "LIQUIDITY_LEVEL"]
    highs = [event.price for event in levels if event.price > price]
    lows = [event.price for event in levels if event.price < price]
    latest_sweep = next((event for event in reversed(visible_liquidity) if event.event_type == "LIQUIDITY_SWEEP"), None)
    time_features = (session_engine or SessionEngine()).time_features(timestamp)
    time_data = asdict(time_features)
    time_data["session"] = time_features.session.value
    if mtf_alignment is not None and mtf_alignment.ltf_timestamp != as_of:
        raise ValueError("MTF alignment timestamp must match snapshot timestamp")
    htf_structure = {
        timeframe: {
            "bias": state.bias.value,
            "score": state.score,
            "last_event": state.last_event_type,
            "last_event_timestamp": state.last_event_timestamp,
        }
        for timeframe, state in (mtf_alignment.states.items() if mtf_alignment else ())
    }
    return {
        "event_timestamp": as_of,
        "symbol": str(value("symbol")),
        "timeframe": str(value("timeframe")),
        "price": price,
        "structure": bias.value,
        "last_bos": last_bos,
        "last_choch": last_choch,
        "nearest_liquidity_high": min(highs) if highs else None,
        "nearest_liquidity_low": max(lows) if lows else None,
        "liquidity_sweep": bool(latest_sweep and latest_sweep.event_timestamp == as_of),
        "htf_structure": htf_structure,
        **time_data,
    }
