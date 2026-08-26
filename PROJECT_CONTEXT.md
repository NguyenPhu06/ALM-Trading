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
- Phase 10 MT5 access is read-only on a DEMO account: no order, modify, close, DCA or SL/TP path exists, and a REAL account is refused outright.
- Phase 11 DEMO execution is gated by three independent switches, all closed by default; a REAL account is refused twice, and no strategy path can reach the execution client.
## Checkpoint Phase 6

Strategy Intelligence & Trade Setup Engine được thiết kế cho research/backtest/paper simulation. Hệ thống giữ HTF bias riêng với LTF structure, phát hiện conflict và chỉ tạo `EXECUTABLE_SIMULATION` sau risk gate. Migration head mới là `20260824_0009`; API chiến lược chỉ có GET. Không có live execution, commit hay push trong phase này.

Do database production chưa đủ lịch sử cho đánh giá ngoài mẫu/walk-forward có ý nghĩa, chưa có bằng chứng về edge: **NO STATISTICAL EDGE DETECTED**.

## Checkpoint Phase 7

Real Market Data Gateway chuẩn hóa provider → quality/store → snapshot/intelligence, hỗ trợ D1/H4/H1/M30/M15/M5 và chỉ dùng candle đã đóng. TradingView/calendar/institutional direct data giữ trạng thái unavailable khi chưa có nguồn hợp pháp. Institutional observations luôn phân biệt proxy. Paper execution là mô phỏng, không có broker route. Migration head Phase 7 là `20260825_0010`.

## Checkpoint Phase 8

Paper Trading Engine có account/equity, position state machine, cost-aware execution, sizing/risk/daily-loss gates, kill switch, bounded DCA, time-exit integration, causal replay, journal và performance. Chỉ setup `EXECUTABLE_SIMULATION` với dữ liệu/provider/model hợp lệ mới được entry. Migration head là `20260825_0011`; không có live order route.

## Checkpoint Phase 11

MT5 DEMO Execution Foundation + manual demo test. **Không** automated trading, **không** strategy auto execution, **không** live trading.

- Ba cổng độc lập, đều đóng mặc định: `DEMO_TRADING_ENABLED=false`, `MT5_EXECUTION_ENABLED=false`, `EXECUTION_KILL_SWITCH=true` (engaged). Thêm `MT5_READ_ONLY=false` và `TRADING_ENVIRONMENT=DEMO`.
- `LIVE_TRADING_ENABLED`, `TRADING_ENVIRONMENT` và `READ_ONLY_MODE` vẫn là startup invariant và vẫn raise. Ba cờ execution chuyển từ startup invariant sang guard check trên từng lệnh, vì nếu không endpoint manual test sẽ không bao giờ chạy được.
- `ExecutionGuard` là cổng bắt buộc với 12 nhóm kiểm tra, fail-closed, trả về mọi lý do cùng lúc. `MT5ExecutionClient` từ chối truyền nếu thiếu approval, approval bị từ chối, hoặc approval thuộc request khác — nên guard không thể bị bỏ qua.
- Account `REAL` bị chặn ở guard và bị chặn lần nữa ngay trước khi truyền. Server phải khớp mẫu DEMO.
- `ExecutionKillSwitch` mặc định engaged, không bao giờ tự nhả, và nhả phải kèm lý do. Tách biệt hoàn toàn với `paper.GlobalKillSwitch`.
- Audit 6 stage cho mọi lệnh kể cả bị từ chối; `scrub()` loại mọi key bí mật trước khi ghi. Reconciliation so request/result/position và chỉ báo cáo, không sửa.
- Migration head là `20260826_0014`; 5 bảng execution, không bảng nào có cột credential.
- Strategy Engine vẫn dừng ở PAPER — test AST khẳng định không module strategy nào tham chiếu execution. Vẫn **NO STATISTICAL EDGE DETECTED**.

## Checkpoint Phase 10

MetaTrader 5 (Exness, DEMO) được tích hợp **READ-ONLY** làm data provider. `MT5ReadOnlyClient` không định nghĩa bất kỳ method thực thi nào; `ReadOnlyExecutionGuard` tồn tại riêng cho interface chung và luôn raise `ReadOnlyModeError`.

- Safety lock hai lớp: `Settings` từ chối khởi tạo với cờ sai, và `MT5SafetyLock` chặn trước khi kết nối (`BLOCK_CONNECTION`) hoặc trước khi đọc (`BLOCK_DATA_ACCESS`). Lock không bao giờ tự sửa cấu hình.
- Tài khoản `REAL` bị chặn và ngắt kết nối; chỉ `DEMO`/`CONTEST` được đọc. `UNKNOWN` bị từ chối.
- Credentials chỉ trong `.env`; password là `SecretStr`; database chỉ lưu login đã mask; `scrub()` loại key bí mật khỏi mọi JSON.
- Symbol được khám phá từ terminal, hỗ trợ suffix/prefix broker; nhiều match không có exact → `SYMBOL_MAPPING_AMBIGUOUS`, không tự chọn.
- Đủ D1/H4/H1/M30/M15/M5, chỉ nến đã đóng, đi qua normalizer chung rồi `MT5DataQualityGate`; dữ liệu INVALID không bao giờ tới strategy.
- `MT5MarketDataProvider` implement `BaseMarketDataProvider` nên MT5 dùng chung pipeline ingestion → feature → intelligence → NN → strategy → **PAPER**.
- Migration head là `20260826_0013`; 8 bảng `mt5_*`, không bảng nào có cột credential.
- Thiếu package/terminal không làm sập hệ thống: `MT5_PACKAGE_NOT_INSTALLED` / `MT5_TERMINAL_NOT_AVAILABLE`.
- MT5 là DATA PROVIDER, không phải EXECUTION PROVIDER. Vẫn **NO STATISTICAL EDGE DETECTED**.

## Checkpoint Phase 9

Command Center là React/TypeScript/Vite frontend observation-only. FastAPI cung cấp 13 dashboard endpoint có timestamp/source/version/quality, system health, freshness và alert history. Frontend không tính strategy và không có order control. Migration head là `20260825_0012`; LIVE và DEMO trading đều bị khóa.

### Phase 9 repair

- DCA đi qua đúng các cổng như entry: `data_quality`, `provider_status` và `prediction` là tham số bắt buộc; drawdown, daily loss và spread được áp dụng; exposure tính trên toàn bộ vị thế đang mở.
- Kill switch từ chối mọi hành động làm tăng exposure (entry và DCA), nhưng không bao giờ chặn REDUCE/CLOSE.
- Alert có một nguồn lưu trữ duy nhất là bảng `dashboard_alerts`; `AlertRouter` nối strategy/risk/paper/data/provider/kill-switch vào alert.
- Freshness được tính thật từ timestamp nguồn; age không xác định luôn là stale.
- `OrchestrationCycle` + `OrchestrationRunner` nối toàn tuyến end-to-end, chỉ dùng nến đã đóng, opt-in qua `phase_9.orchestration.enabled`.
- `PositionStateMachine` và `TimeExitEngine` đã được nối vào vòng đời paper; journal write-back ghi đúng trade vừa đóng.
- Paper account/positions/orders/journals/equity sống sót qua restart nhờ `PaperTradingRepository.load_state()`.
- Không có broker route, không có endpoint live/demo, không có model bịa đặt. Vẫn **NO STATISTICAL EDGE DETECTED**.
