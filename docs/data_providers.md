# Data providers

`BaseMarketDataProvider` isolates connect, disconnect, historical, latest, incremental, and health operations. Provider-specific response formats do not enter features, backtests, strategies, or repositories.

The initial adapter uses Twelve Data's authorized REST API. Its documented time-series API supports FX and the required native intervals, UTC output, bounded date ranges, and up to 5,000 points per request. The adapter chunks larger requests, rate-limits calls, applies finite exponential-backoff retries, sets a timeout, and never writes API keys to logs. See the official [API documentation](https://twelvedata.com/docs), [historical data guide](https://support.twelvedata.com/en/articles/5656039-how-to-get-historical-prices), and [credit model](https://support.twelvedata.com/en/articles/5615854-credits).

Configuration is environment-only:

```text
MARKET_DATA_PROVIDER=historical
MARKET_DATA_API_KEY=
MARKET_DATA_BASE_URL=https://api.twelvedata.com
MARKET_DATA_TIMEOUT=30
MARKET_DATA_RATE_LIMIT=8
MARKET_DATA_MAX_RETRIES=3
MARKET_DATA_BACKOFF_SECONDS=1
```

An absent key produces `UNCONFIGURED`; it never falls back to sample data or TradingView. TradingView remains an isolated webhook/visualization input and is not a canonical machine-readable price feed.

FX volume availability and historical depth depend on the provider/subscription. Missing volume remains `null`; it is not fabricated. The read-only `MT5MarketDataProvider` interface is a future integration boundary and contains no execution methods.
