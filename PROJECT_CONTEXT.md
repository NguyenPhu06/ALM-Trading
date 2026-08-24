# Project context

## Current phase

Phase 1A provides the foundation, Phase 1B adds deterministic market features, and Phase 2 provides trustworthy real-data ingestion. Phase 3 turns closed multi-timeframe data into explainable, versioned Market Intelligence snapshots with structure, liquidity, SMC, indicators, volatility, hierarchical bias, confluence, and NO_TRADE state. Strategy, neural-network training, and live execution remain future work.

## Safety invariants

- Live trading is disabled by configuration and no broker/order execution API exists.
- CFTC COT is periodic public positioning data, not real-time order flow.
- Derived liquidity or institutional-pressure values are estimates, never claims about actual fund orders.
- Invalid source data is rejected and logged; missing candles are detected, not filled.
- Raw webhook and COT records are retained for audit.
- Phase 1B events are causal hypotheses: confirmed swings respect right-bar confirmation, and liquidity/structure concepts do not imply certain institutional activity or future direction.
- Phase 1B.1 explicitly tracks candle close state and permits HTF use only after complete M15-derived H1/H4/D1 buckets close.
- Market regime authority belongs to D1/H4/H1. M15 is liquidity/setup context and cannot automatically override higher-timeframe structure.
- Real market data is imported only through configured provider adapters; sample CSV data remains test-only.
- At simulation time T, a candle is visible only after its complete interval has closed. Native timeframes are preferred over derived data.
- Phase 3 stops at MARKET INTELLIGENCE. Its `signal` is always null and it has no broker execution, order, DCA, or model-training path.
- Confluence is an explainability score, not a statistically validated probability.
- SMC, liquidity, FVG, and order-block labels are deterministic market hypotheses, not claims about hidden institutional intent.
