# Future feature and neural-network compatibility

No model is trained and no random or synthetic feature values are generated in Phase 1A.

The intended feature vector groups are:

- PRICE: returns, ranges, and candle context from `market_candles`.
- LIQUIDITY: derived, timestamped liquidity events.
- STRUCTURE: HH/HL/LH/LL/BOS/CHoCH state known at observation time.
- ICHIMOKU, RSI, ADX, ATR: values written by a future indicator engine.
- TIME: UTC/calendar/session features derived without future information.
- COT: periodic institutional positioning joined only after its publication availability time.
- INSTITUTIONAL PRESSURE: nullable derived estimate with confidence and source metadata.

Future pipeline: database → feature extraction → feature dataset → labeling → train → validation → test → walk-forward evaluation → model prediction. Dataset builders must use point-in-time joins, record data availability (not merely report dates), keep validation/test periods chronologically separate, and prevent look-ahead leakage. `strategy_signals` and `trading_outcomes` provide future signal/label persistence interfaces; neither triggers execution.

