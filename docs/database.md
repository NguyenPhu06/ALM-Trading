# Database architecture

## Candle lifecycle

`market_candles.is_closed` is the Phase 1B.1 causal boundary. Historical CSV imports set it to `true`; normalizer input without an explicit closed state defaults to `false` for live/in-progress safety. Migration `20260824_0003` backfills existing historical records to `true`. Structure, liquidity, resampling, and snapshots never consume an open candle.

ALM uses one repository-controlled persistence path: source adapter → parser → normalizer → validator → repository → PostgreSQL. Collectors never scatter SQL across source modules. The Docker database image is PostgreSQL 17 with the TimescaleDB extension available; Phase 1A uses ordinary PostgreSQL tables and indexes, so migrations remain portable. Converting high-volume tables to hypertables is deliberately deferred until retention, partitioning, and uniqueness policies are agreed.

## Tables and relationships

- `market_candles`: normalized OHLCV data. `(symbol, timeframe, timestamp)` is unique and indexed.
- `market_ticks`: tick interface storage, indexed by symbol/time; realtime ingestion is not active.
- `tradingview_alerts`: validated alert fields plus an audit copy of the source payload. A payload authentication field is removed before storage.
- `liquidity_events`: future ALM-derived events such as swing/equal/session levels and liquidity sweeps.
- `structure_events`: future HH, HL, LH, LL, BOS, CHoCH, and invalidation events.
- `indicator_snapshots`: future indicator-engine output. Collectors do not calculate indicators.
- `cot_reports`: periodic CFTC TFF positioning, unique by report date, market, contract, and source; raw rows are retained.
- `institutional_pressure`: nullable component estimates. Phase 1A creates no values.
- `strategy_signals` and `trading_outcomes`: minimal future dataset/label interfaces. They do not execute trades.

Logical joins use symbol, timeframe, and event/report time. Hard foreign keys are avoided for independently arriving market observations. `trading_outcomes.signal_id` is a future logical reference and is intentionally not populated now.

## Time and precision

All market timestamps must be timezone-aware and are normalized to UTC before validation. PostgreSQL columns use `TIMESTAMP WITH TIME ZONE`; clients must render explicit offsets. Price and volume values use fixed-precision numeric columns rather than binary floats. COT report dates are dates because the data is periodic, not intraday.

## Raw, normalized, and retention data

Raw TradingView JSON and CFTC rows are retained for audit; secrets are never retained. Normalized columns are queryable and validated. Invalid records are logged and rejected rather than silently repaired. No default deletion policy is applied in Phase 1A. Production retention, compression, backups, and Timescale hypertable/chunk policies must be selected from observed volume and regulatory needs before activation.

Migrations are managed by Alembic (`alembic upgrade head`). The database volume `postgres_data` persists across container recreation.
