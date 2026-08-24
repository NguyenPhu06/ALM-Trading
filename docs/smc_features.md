# SMC and price-action features

These definitions are deterministic hypotheses. They do not claim knowledge of market-maker intent or actual institutional order flow.

## Fair value gap and imbalance

For three consecutive closed candles `(i-2, i-1, i)`, a bullish FVG exists when `low[i] > high[i-2]`; its zone is `[high[i-2], low[i]]`. A bearish FVG exists when `high[i] < low[i-2]`; its zone is `[high[i], low[i-2]]`. Size must meet the configured minimum. Subsequent candles update fill percentage from 0 to 100 and state `OPEN`, `PARTIALLY_FILLED`, or `FILLED`. A snapshot before a filling candle remains unchanged.

## Displacement and rejection

True range is compared with rolling ATR. A candle is displaced when `range / ATR` exceeds the configured ratio and `abs(close-open) / range` exceeds the body threshold. Direction is the body direction; volume ratio is included only when real volume exists.

Rejection is the larger wick divided by total range. It is flagged only above the configured wick threshold.

## Order and breaker blocks

The initial order-block rule selects the last opposite candle within a configured lookback before a qualifying displacement candle closes beyond the rolling high or low. Its full high-low range is the zone. A later overlap marks mitigation. If price later closes completely through the opposite zone boundary, it is labeled `BREAKER_BLOCK`.

These zones never create orders automatically.
