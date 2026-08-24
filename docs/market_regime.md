# Multi-timeframe market regime

The regime layer does not treat M15 as the primary trend. Roles are fixed: D1 macro regime, H4 primary structural trend, H1 trading-direction confirmation, M15 liquidity/setup, M5 entry refinement, and M1 optional execution timing. Missing M5/M1 data is explicit and is never manufactured by downsampling.

## Structural matrix

Every timeframe is processed independently through closed candles, delayed swing confirmation, structure, and liquidity. A directional trend requires a structural sequence:

- HH + HL + bullish BOS → bullish;
- LH + LL + bearish BOS → bearish;
- incomplete or conflicting evidence → neutral/transitional.

A single candle, indicator, wick, or M15 CHoCH cannot define the regime. Trends range from `STRONGLY_BEARISH` to `STRONGLY_BULLISH` and include a normalized structural strength.

## HTF and LTF separation

`HTF_BIAS` uses D1/H4/H1 only. `LTF_DIRECTION` uses M15/M5/M1. The configurable structure score defaults to D1 40%, H4 30%, H1 20%, and M15 10%, so lower-timeframe noise cannot dominate the score. Opposing LTF direction is labeled retracement or reversal evidence, never BUY/SELL.

Reversal confidence rises only through a causal sequence: known liquidity sweep, LTF CHoCH, M15 structural confirmation, H1 confirmation, then H4 confirmation. M15 alone remains low confidence.

## Indicators and institutional inputs

RSI, ADX, ATR, and Ichimoku are calculated independently per timeframe from that timeframe's closed candles. They provide confirmation/conflict metadata and never rewrite structural trend. Insufficient history is explicit.

Institutional inputs are optional and timestamped. ALM can consume stored institutional-pressure components or mapped CFTC COT data. Bank participation and CME fields remain unavailable unless real source data exists. Missing values are not synthesized.

## Strategy boundary

Strategies receive `MarketRegimeSnapshot`, not raw candles, for regime decisions. The snapshot contains HTF/LTF direction, market state, reversal confidence, weighted score, liquidity map, isolated indicators, timeframe alignment, and conflicts. `signal` is always null in this phase; the regime engine does not place or recommend trades.
