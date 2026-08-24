# Market structure engine

Phase 1B treats market structure as deterministic feature engineering, not as a prediction or a statement of certainty.

## Causal swing confirmation

`SwingDetector` uses configurable left and right fractal bars; the production Phase 1B.1 pipeline fixes `swing_right_bars=2`. A candidate at candle `i` is not emitted until candle `i + 2` has closed. `confirmation_timestamp` is that candle's close time, not its open time. Downstream calculations may use it only from confirmation onward.

Confirmed highs are classified against the previous confirmed high as `HH` or `LH`. Confirmed lows are classified as `HL` or `LL`. Equal levels use `equal_level_tolerance_points * point_size`; exact floating-point equality is not required.

## BOS and CHoCH

The default `CLOSE_BREAK` mode requires a candle close beyond the confirmed level. `WICK_BREAK` is available through configuration. Each level breaks once:

- a break in the active direction is BOS;
- a break against bearish structure is bullish CHoCH;
- a break against bullish structure is bearish CHoCH.

CHoCH metadata records `previous_structure`, `broken_level`, `new_direction`, break mode, level confirmation time, and deterministic displacement. Unclosed and unconfirmed candles are excluded.

## Higher timeframes

The causal resampler builds H1, H4, and D1 from complete closed M15 buckets in UTC. Open is first, high/low are extrema, close is last, and available volume is summed. Incomplete buckets are never passed into the HTF structure engine.

## Bias and multi-timeframe use

`StructureBias` ranges from `STRONG_BEARISH` to `STRONG_BULLISH`. The score uses only BOS, CHoCH, HH/HL, LH/LL, displacement, and timeframe weighting. No RSI, ADX, Ichimoku, or machine learning is included.

The MTF analyzer keeps HTF bias separate from LTF structure. For example, bullish M15 activity can remain a retracement inside bearish D1/H4/H1 context; it does not relabel the whole market bullish.

Market structure is a market hypothesis and does not provide prediction certainty.
