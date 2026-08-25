from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from data_sources.providers.base import BaseMarketDataProvider, ProviderHealth, ProviderStatus
from database.repositories import CandleRepository

class DatabaseMarketDataProvider(BaseMarketDataProvider):
    """Provider-neutral read gateway over normalized stored market data."""
    name="database";supported_symbols=("EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD","XAUUSD");supported_timeframes=("M5","M15","M30","H1","H4","D1")
    def __init__(self,session):self.repo=CandleRepository(session)
    def connect(self):return None
    def disconnect(self):return None
    @staticmethod
    def _dict(row):
        return {column.name:getattr(row,column.name) for column in row.__table__.columns}
    def fetch_historical(self,symbol,timeframe,start,end):return [self._dict(r) for r in self.repo.chronological(symbol=symbol,timeframe=timeframe,start=start,end=end,closed_only=True)]
    def fetch_latest(self,symbol,timeframe):
        row=self.repo.latest(symbol,timeframe,exclude_sources=("local_csv",));return self._dict(row) if row else None
    def fetch_incremental(self,symbol,timeframe,start,end=None):return self.fetch_historical(symbol,timeframe,start,end or datetime.now(timezone.utc))
    def get_candles(self,symbol,timeframe,*,limit=500):return [self._dict(r) for r in self.repo.recent_chronological(symbol=symbol,timeframe=timeframe,exclude_sources=("local_csv",),closed_only=True,limit=limit)]
    def get_latest_quote(self,symbol):
        for timeframe in ("M5","M15","H1"):
            row=self.fetch_latest(symbol,timeframe)
            if row:
                mid=float(row["close"]);spread=float(row.get("spread") or 0)
                return {"timestamp":row["timestamp"],"symbol":symbol,"bid":mid-spread/2,"ask":mid+spread/2,"mid_price":mid,"spread":spread,"spread_percent":spread/mid if mid else 0,"source":row["source"]}
        return None
    def health_check(self):
        available=any(self.repo.count(symbol=s,timeframe="M15",exclude_sources=("local_csv",)) for s in self.supported_symbols)
        return ProviderStatus(self.name,ProviderHealth.ONLINE if available else ProviderHealth.DEGRADED,None,None if available else "NO_REAL_MARKET_DATA",0.,self.supported_symbols,self.supported_timeframes)

