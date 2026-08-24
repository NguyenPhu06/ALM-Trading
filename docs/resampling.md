# Controlled resampling

Provider-native timeframes are preferred. Resampling is a fallback for a missing native timeframe and is limited to:

- M1 to M5
- M5 to M15
- M15 to H1
- H1 to H4
- H4 to D1

Buckets are UTC aligned and require every expected closed source candle. Open, high, low, close, and volume use first, maximum, minimum, last, and sum respectively. Incomplete or gapped buckets are omitted, not filled. Derived records retain `source_timeframe`, `target_timeframe`, and `UTC_COMPLETE_BUCKET_OHLCV_V1`.

An H1 bucket beginning 10:00 becomes observable only at 11:00. At 10:15 it is excluded even if some M15 components already exist. No later candle is used to construct or expose an earlier decision.
