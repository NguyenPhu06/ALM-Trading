# Market intelligence engine

Phase 3 transforms closed normalized candles into an explainable state. It stops at market intelligence and never emits or executes BUY, SELL, DCA, or broker instructions.

For each of D1, H4, H1, M15, M5, and M1, `MarketIntelligenceEngine` calculates structure, liquidity, SMC/price-action features, indicators, volatility, and causal session statistics. Provider-native database candles are preferred. Test-only `local_csv` sample rows are excluded by default. The controlled Phase 2 resampler is used only when a native timeframe is absent.

At `as_of = T`, a candle is included only when `is_closed = true` and `candle open timestamp + timeframe duration <= T`. Every detector receives exactly that prefix. Appending candles after T therefore cannot alter RSI, ADX, ATR, Ichimoku, BOS, CHoCH, FVG, order blocks, sweeps, bias, confluence, or the feature vector at T.

`MarketStateSnapshot` contains the calculation timestamp, symbol, six independent timeframe states, hierarchical bias, confluence reasons/conflicts, `NO_TRADE` reasons, and a versioned feature vector. `signal` is always null.

Snapshots can be persisted with:

```text
python -m scripts.calculate_market_intelligence --symbol EURUSD --as-of 2026-08-24T09:00:00Z
```

The calculation is deterministic market-state feature engineering, not a prediction or validated trading probability.
