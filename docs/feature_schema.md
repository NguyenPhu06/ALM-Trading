# Versioned feature schema

Every Phase 3 feature includes its calculation timestamp (or `as_of`), symbol, timeframe, and `calculation_version = phase3.v1`. Definitions can therefore change under a new version without silently mixing training datasets.

The stable numeric vector contains, in order:

1. trend encoding for D1, H4, H1, M15, M5, M1 (`-1` bearish, `0` unknown/ranging, `1` bullish);
2. RSI for D1, H4, H1, M15, M5;
3. ADX for D1, H4, H1, M15, M5;
4. ATR for H1, M15, M5;
5. M15 nearest-liquidity distance, sweep direction, FVG distance, and order-block distance;
6. M15 session and volatility-state categorical encodings.

Missing numeric features are encoded as zero and remain distinguishable through the timeframe `available` and indicator `missing_reason` fields in the structured snapshot. Both ordered `names` and `values` are persisted so consumers can reject incompatible schemas.

`market_intelligence_snapshots` stores versioned JSON state and feature vectors keyed by symbol, timeframe, event timestamp, and calculation version. Raw candles are not copied.
