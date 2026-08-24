# Project context

## Current phase

Phase 1A provides the market-data foundation. Phase 1B adds deterministic liquidity, session, swing, market-structure, and multi-timeframe features over closed database candles. Strategy, indicator, neural-network, and live-execution consumers remain future work.

## Safety invariants

- Live trading is disabled by configuration and no broker/order execution API exists.
- CFTC COT is periodic public positioning data, not real-time order flow.
- Derived liquidity or institutional-pressure values are estimates, never claims about actual fund orders.
- Invalid source data is rejected and logged; missing candles are detected, not filled.
- Raw webhook and COT records are retained for audit.
- Phase 1B events are causal hypotheses: confirmed swings respect right-bar confirmation, and liquidity/structure concepts do not imply certain institutional activity or future direction.
- Phase 1B.1 explicitly tracks candle close state and permits HTF use only after complete M15-derived H1/H4/D1 buckets close.
- Market regime authority belongs to D1/H4/H1. M15 is liquidity/setup context and cannot automatically override higher-timeframe structure.
