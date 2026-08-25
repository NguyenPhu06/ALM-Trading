from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai.labels import ForwardMarketLabel


@dataclass(frozen=True, slots=True)
class DatasetRow:
    feature_timestamp: datetime
    symbol: str
    feature_version: str
    features: dict[str, float]
    label: ForwardMarketLabel | None = None

    def __post_init__(self) -> None:
        if self.label and self.label.timestamp != self.feature_timestamp:
            raise ValueError("label must be anchored to the same feature timestamp")
