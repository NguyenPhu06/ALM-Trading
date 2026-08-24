# Look-ahead protection

Phase 1B calculations are causal by construction.

## Rules

1. Candles must be ordered database records with `is_closed=true`. Engines stop at the first open candle even when called outside the pipeline.
2. A fractal candidate is invisible until all configured right-side bars have closed. Production Phase 1B.1 requires two right bars.
3. `event_timestamp` is the first time the event can be known.
4. `confirmation_timestamp` records swing/level confirmation when applicable.
5. Previous-day and previous-session levels appear only after the relevant period transitions.
6. Current-session high/low is running state, never the future final session extreme.
7. MTF and snapshots filter every event at an explicit `as_of` timestamp.
8. The Phase 1B pipeline reads `market_candles` chronologically from the database; it does not manufacture missing candles.
9. M15→H1/H4/D1 aggregation emits only complete UTC buckets. The higher-timeframe `close_time` is its earliest usable time.
10. MTF alignment selects the last event whose event and confirmation timestamps are both at or before the M15 close.

`test_swing_detection_requires_right_confirmation_bar` proves a candidate is unavailable before its right bar. `test_future_extension_cannot_change_past_decisions` compares a prefix calculation with the same prefix inside a longer future series. Snapshot and session tests independently verify that later events and later highs/lows remain invisible.

Backtests should calculate incrementally or pass an `as_of_index`/`as_of` cutoff. Using the final swing list without respecting each event's confirmation timestamp would violate this contract.

Snapshot regression tests compare a snapshot calculated from a candle prefix with the same timestamp calculated after future candles are appended. The results must remain identical.
