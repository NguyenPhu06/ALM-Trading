from __future__ import annotations

from config.settings import Settings, get_settings
from data_sources.providers.base import BaseMarketDataProvider
from data_sources.providers.historical_fx import HistoricalFXProvider


def create_provider(name: str | None = None, *, settings: Settings | None = None) -> BaseMarketDataProvider:
    settings = settings or get_settings()
    provider = (name or settings.market_data_provider).strip().lower()
    if provider in {"historical", "twelve_data", "twelvedata"}:
        return HistoricalFXProvider(
            api_key=settings.market_data_api_key,
            base_url=settings.market_data_base_url,
            timeout=settings.market_data_timeout,
            rate_limit=settings.market_data_rate_limit,
            max_retries=settings.market_data_max_retries,
            backoff_seconds=settings.market_data_backoff_seconds,
        )
    raise ValueError(f"unknown market data provider: {provider}")
