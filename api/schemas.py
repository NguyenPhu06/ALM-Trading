from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from data_quality import DataValidationError
from data_sources.normalizer import normalize_decimal, normalize_symbol, normalize_timeframe, normalize_timestamp


SUPPORTED_EVENTS = {
    "LIQUIDITY_SWEEP", "BOS", "CHOCH", "FVG", "PRICE_ALERT",
    "SESSION_HIGH", "SESSION_LOW", "CUSTOM",
}


class TradingViewWebhook(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    timeframe: str | None = None
    event_type: str = Field(alias="event")
    direction: str | None = None
    price: Decimal | None = None
    event_timestamp: datetime = Field(alias="timestamp")
    secret: str | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def accept_alternate_names(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if "event" not in data and "event_type" in data:
                data["event"] = data["event_type"]
            if "timestamp" not in data and "event_timestamp" in data:
                data["timestamp"] = data["event_timestamp"]
        return data

    @model_validator(mode="after")
    def normalize_and_validate(self) -> "TradingViewWebhook":
        self.symbol = normalize_symbol(self.symbol)
        if self.timeframe is not None:
            self.timeframe = normalize_timeframe(self.timeframe)
        self.event_type = self.event_type.strip().upper()
        if self.event_type not in SUPPORTED_EVENTS:
            raise ValueError(f"unsupported event type; use one of {sorted(SUPPORTED_EVENTS)}")
        if self.direction is not None:
            self.direction = self.direction.strip().upper()
            if not self.direction or len(self.direction) > 32:
                raise ValueError("invalid direction")
        self.event_timestamp = normalize_timestamp(self.event_timestamp)
        if self.price is not None:
            self.price = normalize_decimal(self.price, "price")
        return self


class Pagination(BaseModel):
    offset: int
    limit: int
    items: list[dict[str, Any]]

