# Market data quality

Every incoming batch is normalized and validated before database writes. Validation covers UTC awareness, symbol/timeframe syntax, ascending timestamps, source-aware duplicates, finite positive OHLC prices, OHLC relationships, and non-negative volume, tick volume, and spread.

Invalid batches are rejected as a unit. No random values, forward filling, synthetic prices, or silent repairs are used.

`MarketDataGap` describes the symbol, timeframe, missing range, expected and actual counts, severity, and reason. The detector uses the configured candle interval and the standard UTC FX weekly closure: Friday after 22:00 through Sunday before 22:00 is informational closure, not an ordinary missing-data error. Holiday and provider-specific maintenance calendars are not yet modeled.

`DataFreshness` reports `FRESH`, `STALE`, `MISSING`, or `ERROR` using per-timeframe thresholds in `config/settings.yaml`. Readiness combines count, freshness, recent material gaps, duplicate count, and invalid count. Source-aware uniqueness makes stored same-source duplicates impossible; validation prevents invalid imported candles.
