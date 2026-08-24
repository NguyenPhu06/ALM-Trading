# Real market data engine

Phase 2 makes normalized database candles the canonical input to features, market regime, and backtests. It supports `EURUSD`, `GBPUSD`, `USDJPY`, `USDCHF`, `AUDUSD`, `USDCAD`, and `NZDUSD` at `M1`, `M5`, `M15`, `H1`, `H4`, and `D1`. The lists are configuration, not strategy rules.

All timestamps are timezone-aware UTC. A candle records its source, provider, provider timestamp, ingestion time, and closed state. The database identity is `(symbol, timeframe, timestamp, source)`, so repeated imports are idempotent while independently licensed sources can coexist.

## Historical import

Configure `MARKET_DATA_API_KEY` in `.env`, then run a bounded import:

```text
python -m scripts.import_market_data --provider historical --symbol EURUSD --timeframe M15 --start 2025-01-01 --end 2025-02-01
```

Update only after the latest stored provider candle:

```text
python -m scripts.update_market_data --provider historical --symbol EURUSD --timeframe M15
```

Imports validate the complete response before one transactional upsert. A failed provider request or invalid batch cannot partially replace existing candles. Audit rows in `market_data_ingestions` contain counts, duration, gaps, status, and a sanitized error type.

## APIs

- `GET /api/market-data/candles` supports symbol, timeframe, start, end, source, closed state, limit, and offset.
- `GET /api/market-data/latest` returns the most recent matching candle.
- `GET /api/market-data/health` returns count, latest timestamp, freshness, status, and recent gaps.
- `GET /api/market-data/gaps` returns material recent market-hour gaps.
- `GET /api/market-data/providers` returns configuration/audit health without secrets.
- `GET /api/market-data/readiness` checks all configured symbols and timeframes.

## Sample versus real data

`data/sample/EURUSD_M15_sample.csv` is deterministic **sample data** retained for unit tests and local demonstrations. It is not the default Phase 2 source and must not be represented as real market history. Its `local_csv` source is excluded from real-data health/readiness checks. Real data enters through a configured provider and carries provider provenance.

This subsystem produces data only. It has no route to BUY, SELL, DCA, broker execution, or live orders.
