# Multi-timeframe database data

The Market Regime Engine loads closed D1, H4, H1, M15, M5, and M1 candles from the database. Native provider candles have priority. A controlled derivation chain is used only when a requested native timeframe is absent.

Higher-timeframe authority remains D1/H4/H1. M15/M5/M1 describe lower-timeframe direction, setup, and retracement; they do not redefine the whole market as bullish or bearish.

Backtests use `BacktestDataLoader` with symbol, timeframe, start, end, source, and `as_of`. A row must both have `is_closed=true` and have `timestamp + timeframe duration <= as_of`. Therefore future T+1 candles and unfinished higher-timeframe candles cannot enter a snapshot at T.

The dependency direction remains:

```text
DATA -> FEATURES -> MARKET REGIME -> STRATEGY -> RISK -> EXECUTION
```

Phase 2 implements only DATA and the safe read boundary. It does not train machine-learning models or invoke execution.
