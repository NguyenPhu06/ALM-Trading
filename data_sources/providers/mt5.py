from __future__ import annotations

from abc import ABC

from data_sources.providers.base import BaseMarketDataProvider


class MT5MarketDataProvider(BaseMarketDataProvider, ABC):
    """Future read-only MT5 market-data interface; contains no execution methods."""
