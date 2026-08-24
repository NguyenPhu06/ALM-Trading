# Liquidity engine

The Phase 1B liquidity engine derives auditable hypotheses from candles already stored in PostgreSQL/TimescaleDB. Liquidity does not mean a guaranteed institutional order, and a liquidity sweep does not guarantee reversal.

## Levels

The engine emits `LIQUIDITY_LEVEL` events for:

- confirmed swing highs and lows;
- tolerance-based equal highs and lows;
- previous-day high and low, available only at the first observed candle of the next UTC day;
- current running session high and low;
- previous completed session high and low.

Sessions are configurable and calculated in the configured IANA timezone while persisted timestamps remain UTC. Default windows are Asia 00:00–09:00, London 07:00–16:00, and New York 13:00–22:00 UTC. London/New York concurrency is labeled `LONDON_NEW_YORK_OVERLAP` (`OVERLAP` remains a compatible enum alias).

## Sweeps

A bearish sweep requires a previously known high level, a wick above it, a close back below it, and a configurable minimum rejection ratio. A bullish sweep applies the inverse conditions to a known low. Metadata includes level, penetration, rejection, rejection ratio, `close_back_inside`, level-known time, and age in bars. A wick away from a known level is not a sweep.

## Strength

The 0–100 score is deterministic. Its bounded components are normalized distance, touch count, age, timeframe weight, equal-level status, swing strength, and session relevance. It is feature engineering only; no model is fitted and no synthetic AI training data is created.

SMC/ICT terminology in ALM represents testable market hypotheses, not established facts about market-maker behavior.
