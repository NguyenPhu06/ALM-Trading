from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Sequence

from features.structure import MarketStructureEngine, StructureBias, StructureEventData


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TimeframeBias:
    timeframe: str
    bias: StructureBias
    score: float
    weight: float


@dataclass(frozen=True, slots=True)
class MTFStructureBias:
    htf_bias: StructureBias
    ltf_structure: StructureBias
    combined_bias: StructureBias
    score: float
    timeframes: tuple[TimeframeBias, ...]


class MTFStructureAnalyzer:
    WEIGHTS = {"M1": 0.5, "M5": 0.75, "M15": 1.0, "M30": 1.25, "H1": 2.0, "H4": 3.0, "D1": 4.0, "W1": 5.0, "MN1": 6.0}
    HTF = {"H1", "H4", "D1", "W1", "MN1"}

    def calculate(
        self,
        events_by_timeframe: Mapping[str, Sequence[StructureEventData]],
        *,
        as_of: datetime | None = None,
    ) -> MTFStructureBias:
        details: list[TimeframeBias] = []
        for timeframe, events in events_by_timeframe.items():
            visible = [
                event for event in events
                if as_of is None or (
                    event.event_timestamp <= as_of
                    and (event.confirmation_timestamp is None or event.confirmation_timestamp <= as_of)
                )
            ]
            bias, score = MarketStructureEngine.bias(visible)
            details.append(TimeframeBias(timeframe, bias, score, self.WEIGHTS.get(timeframe, 0.5)))
        details.sort(key=lambda item: item.weight, reverse=True)
        htf = [item for item in details if item.timeframe in self.HTF]
        ltf = [item for item in details if item.timeframe not in self.HTF]
        htf_bias, htf_score = self._weighted(htf)
        ltf_bias, _ = self._weighted(ltf)
        combined, combined_score = self._weighted(details)
        logger.info("MTF synchronization: timeframes=%d htf=%s ltf=%s", len(details), htf_bias, ltf_bias)
        return MTFStructureBias(htf_bias, ltf_bias, combined, combined_score, tuple(details))

    @staticmethod
    def _weighted(items: Sequence[TimeframeBias]) -> tuple[StructureBias, float]:
        if not items:
            return StructureBias.NEUTRAL, 0.0
        total_weight = sum(item.weight for item in items)
        score = sum(item.score * item.weight for item in items) / total_weight
        if score >= 60:
            bias = StructureBias.STRONG_BULLISH
        elif score >= 20:
            bias = StructureBias.BULLISH
        elif score <= -60:
            bias = StructureBias.STRONG_BEARISH
        elif score <= -20:
            bias = StructureBias.BEARISH
        else:
            bias = StructureBias.NEUTRAL
        return bias, round(score, 2)
