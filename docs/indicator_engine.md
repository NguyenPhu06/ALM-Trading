# Indicator engine

Indicators are calculated independently per timeframe over its closed causal prefix.

- RSI(14): arithmetic mean of the last 14 gains and losses, `100 - 100/(1 + average_gain/average_loss)`. Features include thresholds, midline side, one-step slope, oversold recovery, deterministic close/RSI divergence, and possible exhaustion.
- ATR(14): arithmetic mean of the last 14 true ranges, where `TR = max(high-low, |high-prev_close|, |low-prev_close|)`.
- ADX(14): rolling positive/negative directional movement divided by true-range sum, followed by the mean of the last 14 DX values. It exposes `+DI`, `-DI`, direction, rising/falling, and `NO_TREND`, `WEAK_TREND`, `MODERATE_TREND`, or `STRONG_TREND`.
- Volatility: ATR percentage, population standard deviation of close returns, and the latest range percentile. Percentile bands map to low, normal, high, or extreme volatility.

Ichimoku defaults are Tenkan 9, Kijun 26, Senkou B 52, displacement 26. Tenkan/Kijun and newly calculated leading spans use data available now. Cloud comparisons at the current candle use spans calculated 26 bars earlier; future-shifted plot coordinates are never read as current information. Chikou exposes the current known close together with its calculation timestamp, rather than reading a future close at the backward plot position.
