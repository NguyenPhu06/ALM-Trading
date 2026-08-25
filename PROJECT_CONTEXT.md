# Project context

## Current phase

Phase 1A provides the foundation, Phase 1B adds deterministic market features, and Phase 2 provides trustworthy real-data ingestion. Phase 3 creates explainable Market Intelligence. Phase 4 creates immutable causal ML datasets. Phase 5 adds majority/logistic/tree baselines, a reproducible NumPy MLP, chronological training and early stopping, walk-forward validation, multiclass/calibration/trading-relevant evaluation, immutable model registry/cards, JSON experiment tracking, and prediction-only inference. Production training remains blocked until a real Phase 4 dataset passes readiness; live execution remains future work.

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
- Future candles are permitted only inside offline label generation, never inside features at the same timestamp.
- DCA and time exits are simulations with audit records; they have no broker or order route.
- Phase 4 features stop at T; only offline labels can inspect T+1 through T+10.
- Validation/test data never participates in scaler fitting, and time-series partitions are never shuffled.
- Dataset IDs and content/schema hashes are immutable; an older dataset is never overwritten.
- Phase 5 fits only TRAIN, uses VALIDATION for early stopping, and reserves TEST for final evaluation rather than hyperparameter tuning.
- Model confidence is not treated as calibrated probability without calibration evidence.
- Neural inference returns probabilities and structured context only; it cannot create orders or bypass risk.
## Checkpoint Phase 6

Strategy Intelligence & Trade Setup Engine được thiết kế cho research/backtest/paper simulation. Hệ thống giữ HTF bias riêng với LTF structure, phát hiện conflict và chỉ tạo `EXECUTABLE_SIMULATION` sau risk gate. Migration head mới là `20260824_0009`; API chiến lược chỉ có GET. Không có live execution, commit hay push trong phase này.

Do database production chưa đủ lịch sử cho đánh giá ngoài mẫu/walk-forward có ý nghĩa, chưa có bằng chứng về edge: **NO STATISTICAL EDGE DETECTED**.

## Checkpoint Phase 7

Real Market Data Gateway chuẩn hóa provider → quality/store → snapshot/intelligence, hỗ trợ D1/H4/H1/M30/M15/M5 và chỉ dùng candle đã đóng. TradingView/calendar/institutional direct data giữ trạng thái unavailable khi chưa có nguồn hợp pháp. Institutional observations luôn phân biệt proxy. Paper execution là mô phỏng, không có broker route. Migration head Phase 7 là `20260825_0010`.
