# ALM-Trading

## Phase 11 — MT5 DEMO Execution Foundation

Phase 11 xây **nền tảng execution** cho MT5 DEMO và **một manual test**. Không có automated trading, không có strategy auto execution, không có live trading.

Một lệnh chỉ đi được khi **cả ba cổng** đều mở, và cả ba đều **đóng theo mặc định**: `DEMO_TRADING_ENABLED=false`, `MT5_EXECUTION_ENABLED=false`, `EXECUTION_KILL_SWITCH=true`. `LIVE_TRADING_ENABLED` vẫn raise ngay khi khởi động nếu bật. Account `REAL` bị chặn hai lần — ở `ExecutionGuard` và một lần nữa ngay trước khi truyền.

`ExecutionGuard` là cổng bắt buộc: `MT5ExecutionClient` từ chối truyền nếu không có `GuardDecision` khớp `request_id`, nên bỏ qua guard **không hoạt động**. Mọi lệnh — kể cả bị từ chối — được audit đủ 6 stage và đối soát với position thật.

Strategy Engine vẫn dừng ở **PAPER**; nó không có đường nào tới MT5 execution.

Tài liệu: [DEMO execution](docs/demo_execution.md), [execution guard](docs/execution_guard.md), [kill switch](docs/kill_switch.md), [reconciliation](docs/reconciliation.md).

## Phase 10 — MT5 Exness Read-Only Integration

Phase 10 kết nối MetaTrader 5 (Exness, tài khoản **DEMO**) làm **DATA PROVIDER**: account, symbol, tick, candle D1→M5, spread, positions, orders và history. MT5 **không phải** execution provider — không gửi lệnh, không sửa lệnh, không đóng position, không DCA thật, không SL/TP thật.

Safety lock bắt buộc: `TRADING_ENVIRONMENT=DEMO`, `MT5_READ_ONLY=true`, `MT5_EXECUTION_ENABLED=false`, `LIVE_TRADING_ENABLED=false`, `DEMO_TRADING_ENABLED=false`, `READ_ONLY_MODE=true`. Sai cấu hình → `BLOCK_CONNECTION` / `BLOCK_DATA_ACCESS`. Tài khoản `REAL` bị chặn và ngắt kết nối ngay.

Credentials (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`) chỉ nằm trong `.env`, không vào source/log/database/API. Login luôn hiển thị dạng mask.

Package `MetaTrader5` chỉ chạy trên Windows cùng máy với terminal; khi thiếu, hệ thống báo `MT5_TERMINAL_NOT_AVAILABLE` và **không sập**.

Tài liệu: [MT5 read-only](docs/mt5_readonly.md), [data pipeline](docs/mt5_data_pipeline.md), [Windows bridge](docs/mt5_windows_bridge.md), [security](docs/mt5_security.md).

## Phase 9 — Trading Command Center

Phase 9 thêm React/TypeScript/Vite dashboard quan sát MTF, liquidity, indicators, NN, strategy/risk explanation, paper positions/DCA, journal, equity/performance, system health và alerts. Dashboard chỉ hiển thị backend decisions; không có MT5, Exness, broker hoặc execution control. `LIVE_TRADING_ENABLED=false`, `DEMO_TRADING_ENABLED=false`.

Phase 9 cũng thêm vòng lặp orchestration nhỏ nhất để hệ thống chạy end-to-end: provider → validation → snapshot → intelligence → AI (tùy chọn) → strategy → risk → paper → persistence → alerts → dashboard. Vòng lặp là **opt-in** (`phase_9.orchestration.enabled: false`); khởi động API không tự khởi động hoạt động giao dịch. Khi chưa có model đã train, hệ thống giữ nguyên hành vi `MODEL_UNAVAILABLE` và không vào lệnh.

Mở dashboard tại `http://localhost:3000` sau `docker compose up -d --build`. Chạy một tick thủ công: `python -m scripts.run_orchestrator --once`.

Tài liệu: [dashboard](docs/dashboard.md), [orchestration](docs/orchestration.md), [monitoring](docs/monitoring.md), [alerting](docs/alerting.md), [trade explainability](docs/trade_explainability.md).

## Phase 8 — Paper Trading Engine

Phase 8 thêm account/position/order thuần mô phỏng, execution costs, sizing, risk/daily-loss gate, kill switch, DCA/time exit, causal replay, journal và performance dashboard. `PAPER_TRADING_ENABLED=true`, `LIVE_TRADING_ENABLED=false`; không có broker live-order route.

Tài liệu: [paper trading](docs/paper_trading.md), [risk](docs/paper_risk_management.md), [execution](docs/paper_execution.md), [replay](docs/paper_replay.md), [journal](docs/trade_journal.md).

## Phase 7 — Real Market Data Gateway

Phase 7 thêm gateway dữ liệu thị trường thật/near-real-time, provider health, cache TTL, quality gate, snapshot đa khung, COT context, calendar/news-risk contracts và paper execution thuần mô phỏng. TradingView không bị scrape; dữ liệu tổ chức không được bịa. `LIVE_TRADING_ENABLED=false`.

Tài liệu: [kiến trúc market data](docs/market_data_architecture.md), [providers](docs/providers.md), [TradingView](docs/tradingview.md), [COT](docs/cot.md), [institutional data](docs/institutional_data.md), [economic calendar](docs/economic_calendar.md), [paper trading](docs/paper_trading.md).

## Phase 6 — Strategy Intelligence (research-only)

Phase 6 thêm đánh giá setup đa khung D1/H4/H1/M30/M15/M5, scoring có giải thích, risk gate, DCA/time-exit mô phỏng và backtest có transaction costs. API Phase 6 hoàn toàn chỉ đọc. `LIVE_TRADING_ENABLED=false`; dự án không kết nối broker để đặt lệnh.

Tài liệu: [Strategy Engine](docs/strategy_engine.md), [Trade Setup](docs/trade_setup.md), [DCA](docs/dca_strategy.md), [Time Exit](docs/time_exit.md), [Backtest](docs/strategy_backtest.md), [Explainability](docs/strategy_explainability.md).

ALM-Trading is an FX market research and analysis system. Phase 5 adds a research-only baseline, Neural Network, evaluation, model-registry, and inference layer over immutable Phase 4 datasets.

This phase does **not** connect to trading accounts, place orders, or manufacture institutional data. Neural-network training is permitted only on a Phase 4 dataset that passes readiness; `LIVE_TRADING_ENABLED` remains `false`.

Phase 1B adds deterministic liquidity, session, swing, BOS/CHoCH, structure-bias, and multi-timeframe features. See [market structure](docs/market_structure.md), [liquidity engine](docs/liquidity_engine.md), and [look-ahead protection](docs/lookahead_protection.md).

The corrected multi-timeframe architecture keeps D1/H4/H1 regime separate from M15/M5/M1 direction. See [market regime](docs/market_regime.md). The read-only snapshot API is `GET /api/regime`.

Phase 2 supports seven major FX pairs at M1/M5/M15/H1/H4/D1. See [market data](docs/market_data.md), [providers](docs/data_providers.md), [quality](docs/data_quality.md), [resampling](docs/resampling.md), and [MTF data](docs/mtf_data.md).

Phase 3 combines causal D1/H4/H1/M30/M15/M5/M1 structure, liquidity, SMC/price action, indicators, volatility, and sessions into explainable versioned snapshots. It also provides per-candle features, offline label schemas, and constrained backtest/DCA simulation. See [market intelligence](docs/market_intelligence.md), [feature engineering](docs/feature_engineering.md), [data pipeline](docs/data_pipeline.md), [backtest simulation](docs/backtest_simulation.md), and [neural-network plan](docs/neural_network_plan.md).

Phase 4 builds EURUSD-first D1/H4/H1/M30/M15/M5 datasets with data-quality reports, close-time MTF alignment, 58 versioned features, configurable forward labels, chronological splits, TRAIN-only normalization, walk-forward windows, immutable hashes, Parquet export, and readiness checks. See [ML dataset](docs/ml_dataset.md), [data leakage](docs/data_leakage.md), [labeling](docs/labeling.md), and [walk-forward](docs/walk_forward.md).

Phase 5 compares majority/logistic/tree baselines with a reproducible NumPy MLP, tracks class imbalance, early stopping, overfitting, multiclass metrics, calibration, walk-forward results, immutable model cards, and prediction-only inference. See [Neural Network](docs/neural_network.md), [model evaluation](docs/model_evaluation.md), [model registry](docs/model_registry.md), and [model risk](docs/model_risk.md). Production training is currently refused because no real Phase 4 dataset is ready.

## Quick start

1. Copy `.env.example` to `.env`; replace the database password and webhook secret, and add an authorized `MARKET_DATA_API_KEY` for real imports.
2. Run `docker compose up -d`.
3. Apply migrations: `docker compose exec api alembic upgrade head`.
4. Import a bounded real dataset: `docker compose exec api python -m scripts.import_market_data --provider historical --symbol EURUSD --timeframe M15 --start 2025-01-01 --end 2025-02-01`.
5. Increment later: `docker compose exec api python -m scripts.update_market_data --provider historical --symbol EURUSD --timeframe M15`.
6. Calculate Phase 1B events: `docker compose exec api python -m scripts.calculate_phase1b --symbol EURUSD --timeframe M15`.
7. Calculate a snapshot: `docker compose exec api python -m scripts.calculate_market_intelligence --symbol EURUSD`.
8. Build a historical ML dataset: `docker compose exec api python scripts/build_ml_dataset.py --symbol EURUSD`.
9. Check readiness: `docker compose exec api python scripts/check_ml_dataset.py`.
10. Train only after readiness passes: `docker compose exec api python scripts/train_model.py`.
11. Evaluate an immutable model: `docker compose exec api python scripts/evaluate_model.py MODEL_VERSION METADATA_PATH`.
12. Open `http://localhost:8000/docs`.

The sample CSV import remains available for deterministic tests only: `python -m scripts.import_sample_data`.

Useful commands:

```text
python -m pytest -q
pip install MetaTrader5      # Windows only, for the Phase 10 live integration
docker compose config
python -m scripts.update_cot
python -m scripts.test_tradingview_webhook
```

See [database architecture](docs/database.md) and [data-source classifications](docs/data_sources.md).
