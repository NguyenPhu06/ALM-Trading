# ALM-Trading

ALM-Trading is an FX market research and analysis system. Phase 3 adds a deterministic Market Intelligence Engine over the provider-neutral Phase 2 data foundation.

This phase does **not** connect to trading accounts, place orders, train neural networks, or manufacture institutional data. `LIVE_TRADING_ENABLED` must remain `false`.

Phase 1B adds deterministic liquidity, session, swing, BOS/CHoCH, structure-bias, and multi-timeframe features. See [market structure](docs/market_structure.md), [liquidity engine](docs/liquidity_engine.md), and [look-ahead protection](docs/lookahead_protection.md).

The corrected multi-timeframe architecture keeps D1/H4/H1 regime separate from M15/M5/M1 direction. See [market regime](docs/market_regime.md). The read-only snapshot API is `GET /api/regime`.

Phase 2 supports seven major FX pairs at M1/M5/M15/H1/H4/D1. See [market data](docs/market_data.md), [providers](docs/data_providers.md), [quality](docs/data_quality.md), [resampling](docs/resampling.md), and [MTF data](docs/mtf_data.md).

Phase 3 combines causal structure, liquidity, SMC/price action, indicators, volatility, and sessions into explainable versioned snapshots. See [market intelligence](docs/market_intelligence.md), [SMC features](docs/smc_features.md), [indicators](docs/indicator_engine.md), [confluence](docs/confluence.md), and [feature schema](docs/feature_schema.md).

## Quick start

1. Copy `.env.example` to `.env`; replace the database password and webhook secret, and add an authorized `MARKET_DATA_API_KEY` for real imports.
2. Run `docker compose up -d`.
3. Apply migrations: `docker compose exec api alembic upgrade head`.
4. Import a bounded real dataset: `docker compose exec api python -m scripts.import_market_data --provider historical --symbol EURUSD --timeframe M15 --start 2025-01-01 --end 2025-02-01`.
5. Increment later: `docker compose exec api python -m scripts.update_market_data --provider historical --symbol EURUSD --timeframe M15`.
6. Calculate Phase 1B events: `docker compose exec api python -m scripts.calculate_phase1b --symbol EURUSD --timeframe M15`.
7. Calculate a snapshot: `docker compose exec api python -m scripts.calculate_market_intelligence --symbol EURUSD`.
8. Open `http://localhost:8000/docs`.

The sample CSV import remains available for deterministic tests only: `python -m scripts.import_sample_data`.

Useful commands:

```text
python -m pytest -q
docker compose config
python -m scripts.update_cot
python -m scripts.test_tradingview_webhook
```

See [database architecture](docs/database.md) and [data-source classifications](docs/data_sources.md).
