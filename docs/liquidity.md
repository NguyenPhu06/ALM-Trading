# Phase 3 liquidity features

Liquidity levels are measurable price references, not proof of institutional orders. The engine exposes confirmed swing highs/lows, equal highs/lows, previous day/week/month extremes, running current-session extremes, previous-session extremes, and clustered liquidity pools.

Two confirmed same-side swings belong to a pool when each consecutive price difference is at most `equal_level_tolerance_points × point_size`. A high cluster is labeled buy-side liquidity; a low cluster is sell-side liquidity. Pool strength is a bounded deterministic function of distance, touches, age, timeframe, equality, swing prominence, and session relevance.

A high-side sweep requires `high > level`, `close < level`, and upper-wick rejection divided by candle range greater than the configured minimum. It is a bearish rejection of buy-side liquidity. A low-side sweep symmetrically requires `low < level`, `close > level`, and sufficient lower-wick rejection. Each event records penetration, rejection, rejection ratio, level-known timestamp, direction, timeframe, and strength.

A wick alone is not a sweep. Levels become active only at their causal confirmation timestamp, and later filling/rejection cannot be written into an earlier snapshot.
