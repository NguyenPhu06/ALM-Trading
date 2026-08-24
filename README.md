# ALM-Trading

ALM-Trading is an FX market research and analysis system. Phase 1A provides a safe, auditable market-data foundation: collectors feed normalized and validated records through repositories into PostgreSQL/TimescaleDB, and FastAPI exposes paginated read APIs.

This phase does **not** connect to trading accounts, place orders, train neural networks, or manufacture institutional data. `LIVE_TRADING_ENABLED` must remain `false`.

Phase 1B adds deterministic liquidity, session, swing, BOS/CHoCH, structure-bias, and multi-timeframe features. See [market structure](docs/market_structure.md), [liquidity engine](docs/liquidity_engine.md), and [look-ahead protection](docs/lookahead_protection.md).

The corrected multi-timeframe architecture keeps D1/H4/H1 regime separate from M15/M5/M1 direction. See [market regime](docs/market_regime.md). The read-only snapshot API is `GET /api/regime`.

## Quick start

1. Copy `.env.example` to `.env` and replace the database password and webhook secret.
2. Run `docker compose up -d`.
3. Apply migrations: `docker compose exec api alembic upgrade head`.
4. Import sample candles: `docker compose exec api python -m scripts.import_sample_data`.
5. Calculate Phase 1B events: `docker compose exec api python -m scripts.calculate_phase1b --symbol EURUSD --timeframe M15`.
6. Open `http://localhost:8000/docs`.

Useful commands:

```text
python -m pytest
docker compose config
python -m scripts.update_cot
python -m scripts.test_tradingview_webhook
```

See [database architecture](docs/database.md) and [data-source classifications](docs/data_sources.md).
