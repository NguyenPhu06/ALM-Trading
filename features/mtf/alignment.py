from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from features.candles import candle_close_time
from features.structure import MarketStructureEngine, StructureBias, StructureEventData


@dataclass(frozen=True, slots=True)
class ConfirmedTimeframeState:
    timeframe: str
    as_of: datetime
    bias: StructureBias
    score: float
    last_event_type: str | None
    last_event_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class MTFAlignment:
    ltf_timestamp: datetime
    states: dict[str, ConfirmedTimeframeState]


class MTFAlignmentEngine:
    TIMEFRAMES = ("H1", "H4", "D1")

    def state_at(
        self,
        ltf_candle: object,
        events_by_timeframe: Mapping[str, Sequence[StructureEventData]],
    ) -> MTFAlignment:
        as_of = candle_close_time(ltf_candle)
        states: dict[str, ConfirmedTimeframeState] = {}
        for timeframe in self.TIMEFRAMES:
            visible = [
                event for event in events_by_timeframe.get(timeframe, ())
                if event.event_timestamp <= as_of
                and (event.confirmation_timestamp is None or event.confirmation_timestamp <= as_of)
            ]
            bias, score = MarketStructureEngine.bias(visible)
            latest = max(visible, key=lambda event: event.event_timestamp) if visible else None
            states[timeframe] = ConfirmedTimeframeState(
                timeframe, as_of, bias, score,
                latest.event_type if latest else None,
                latest.event_timestamp if latest else None,
            )
        return MTFAlignment(as_of, states)

    def align(
        self,
        ltf_candles: Sequence[object],
        events_by_timeframe: Mapping[str, Sequence[StructureEventData]],
    ) -> list[MTFAlignment]:
        return [self.state_at(candle, events_by_timeframe) for candle in ltf_candles]
