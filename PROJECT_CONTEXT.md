# Project context

## Current phase

Phase 1A provides the foundation, Phase 1B adds deterministic market features, and Phase 2 provides trustworthy real-data ingestion. Phase 3 creates explainable Market Intelligence. Phase 4 creates immutable causal ML datasets. Phase 5 adds majority/logistic/tree baselines, a reproducible NumPy MLP, chronological training and early stopping, walk-forward validation, multiclass/calibration/trading-relevant evaluation, immutable model registry/cards, JSON experiment tracking, and prediction-only inference. Production training remains blocked until a real Phase 4 dataset passes readiness; live execution remains future work. Phase 13 adds the forward-only learning loop — versioned datasets, cost-aware forward labelling, chronological splits, a multi-task network, rule baselines, segmented and calibration metrics, a champion/challenger registry, drift flagging and permutation explainability. Learning happens only through an explicit training job; promotion requires human approval; no part of it can enable execution. Phase 14 runs that loop continuously: a scheduled, idempotent, restart-safe observation driver, forward outcomes measured net of cost, an eleven-class error taxonomy, rolling and segmented performance, and a four-verdict edge detector that accepts forward evidence only. Phase 15 adds the research lab: a strategy registry, eight configured experiments, a nine-arm ablation, regime/session/timeframe matrices, DCA and exit studies, an NN value test, a five-gate strategy champion/challenger, multiple-testing correction and a single-use holdout. Phase 16 adds controlled MT5 DEMO trading: explicit execution modes with OBSERVATION as the default, a twelve-gate fail-closed chain in front of the Phase 11 ExecutionGuard, derived position sizing, deterministic idempotency, manual approval, a trading-day risk budget, reconciliation as a safe shutdown, a full trade journal and forward feedback into the observation store. LIVE trading and REAL-account execution remain refused at startup. Phase 17 adds DEMO validation and shadow trading: a SHADOW mode that runs the identical pipeline and stops before the broker call, a shadow record for every DEMO candidate, a nine-difference SHADOW/DEMO attribution, execution/signal/model quality, regime/session/timeframe cuts, seven rolling windows behind configurable sample floors, eight performance gates that can never enable execution, a computed and purely advisory automation eligibility, an eleven-trigger circuit breaker whose recovery needs four checks and a named human, nine anomaly detectors, and daily and weekly reviews.

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
- Phase 12 observation mode is the outermost block: the full pipeline runs against the live market and the terminal stage is always a recorded simulation with orders_sent = 0.
- Phase 13 learning is forward-only and offline: no `fit()` is reachable from the observation loop, `AI_ONLINE_LEARNING_ENABLED=false` and `AI_AUTO_PROMOTE=false` are enforced by startup validators, and training or promoting a model changes no execution flag.
- The neural network supplies probabilities only. It is one weighted component of the Strategy Engine (`nn_alignment < 0.5`) and reaches neither the Risk Engine, the Execution Guard nor the kill switch; no module under `ai/` may reference an execution symbol.
- A label exists only after its horizon has actually elapsed. Movement smaller than trading cost is NEUTRAL, not an opportunity.
- Model artifacts live outside Git and are credential-scrubbed at every depth before being written; no registry table holds a binary or a credential column.
- Drift detection is FLAG_ONLY: it never retrains, never demotes a champion and never alters a threshold.
- The Phase 14 driver observes and nothing else: it holds no execution client, imports no execution module, and refuses to start while any execution gate is open.
- A cycle id is sha256(symbol | timeframe | candle) — deterministic across processes, timezones and restarts — so re-running a candle is a duplicate rather than a second observation.
- An observation advances one lifecycle step at a time; skipping, repeating or reversing a step raises. The four failure states are terminal.
- Performance is always net of spread, commission, slippage and swap. Gross PnL is never the headline figure.
- `future_return` is signed by the observed direction; the market's direction is read from the raw price move, so a profitable SELL is not recorded as a wrong prediction.
- An edge claim requires forward-observation evidence and must beat nine baselines. Positive PnL alone is never an edge, and UNSTABLE_EDGE is not an edge.
- Training remains manual: AI_AUTOMATIC_TRAINING is refused at startup and no loop module can import a trainer.
- Research reads and reports; it never executes. No module under `research/` imports an execution or paper package, holds a broker handle, or writes a setting.
- A registry entry is a declaration of rules, not an executable object; it reports `executes: false`.
- CHAMPION is unreachable by state transition. Promotion requires an ApprovalToken carrying a named human and a stated reason, and it retires the incumbent.
- Research defaults are negative: a component does not improve the strategy, the NN's value is not proven, DCA does not help, and there is no edge until each is demonstrated.
- Evidence provenance is checked per row: one backtest observation mixed into a forward set is refused by name rather than averaged in.
- Apparent edge grows with the number of strategies tried, so every hypothesis is counted and the significance bar is corrected for the count.
- Phase 16 DEMO execution is DEMO-only by construction: `REAL_ACCOUNT_EXECUTION` and `LIVE_TRADING_ENABLED` are refused at startup, a REAL account is refused in four independent places, and no live adapter exists.
- OBSERVATION remains the default execution mode after Phase 16, and there is no endpoint that changes the mode, opens a flag or arms execution.
- The mode never switches itself. A closed gate blocks the order, not the mode; an unknown mode string is refused rather than coerced to a default.
- Twelve gates run per order, all of them, all fail-closed. An input that cannot be evaluated blocks, with the single documented exception that a missing NN prediction is advisory rather than fatal.
- There is no arbitrary lot size. Volume is derived from equity, risk, stop distance and tick economics; a risk budget below one lot is a refusal, not a rounding up.
- A DCA order re-runs the complete gate chain, is bounded in levels and aggregate exposure, and is never sized by a multiplier on a loss.
- `request_id` is derived from the decision, so a repeat submission is recognised rather than improbable; a gate-blocked proposal never reached a broker and may be retried.
- A reconciliation mismatch engages the kill switch. An emergency shutdown blocks new orders and never closes an open position; `positions_closed` is a column that is always false.
- An even-hour checkpoint re-evaluates a position; it does not close one. Every exit records one of eight declared reasons.
- A closed DEMO trade is recorded in the observation/performance store tagged `DEMO_EXECUTION` and nothing else: `retrained` is a constant false.
- SHADOW is not a second pipeline. A shadow record is minted from the same `GateChainDecision` the DEMO path produced, so the two cannot drift apart; `ShadowRecorder` holds no client, guard, connection or gate chain.
- The twelve gates split into DECISION and TRANSMISSION. SHADOW and DEMO must agree on every decision gate; they differ only on transmission, and that difference is the mode.
- Every DEMO candidate produces a shadow record — approved, blocked or awaiting approval. The blocked ones are the population the gates removed, and they are kept.
- `shadow_signals.orders_sent`, `circuit_breaker_events.positions_closed` and `performance_gates.enabled_execution` are written as pinned constants, so an upstream bug cannot record the opposite.
- Nothing under `validation/` holds an execution client or writes a setting; both are asserted by parsing the package.
- A failed performance gate never enables higher-risk execution, and an unmeasured gate is UNKNOWN rather than PASS.
- `DEMO_AUTOMATION_ELIGIBLE` is computed and advisory. Being eligible changes no flag; `DEMO_AUTOMATION_APPROVED` records a human decision and is not sufficient on its own.
- The circuit breaker is independent of the kill switch, so releasing the switch is not a way around the recovery checklist. Recovery needs a health check, a risk check, account validation and a named human; there is no timeout and no automatic reset.
- Tripping the breaker blocks new orders and never closes an open position.
- An anomaly raises an alert and stops nothing. Section 21 alerts; section 22 stops.
- A rolling window longer than the available history reports INSUFFICIENT_DATA rather than a number, and an edge in one window alone is UNSTABLE_EDGE.
- The even-hour policy and DCA both default to not proven. DCA is rejected when a higher win rate is bought with materially worse tail risk.
- The holdout is the most recent chronological tail, read once. A second read marks the final result invalid.
## Checkpoint Phase 6

Strategy Intelligence & Trade Setup Engine được thiết kế cho research/backtest/paper simulation. Hệ thống giữ HTF bias riêng với LTF structure, phát hiện conflict và chỉ tạo `EXECUTABLE_SIMULATION` sau risk gate. Migration head mới là `20260824_0009`; API chiến lược chỉ có GET. Không có live execution, commit hay push trong phase này.

Do database production chưa đủ lịch sử cho đánh giá ngoài mẫu/walk-forward có ý nghĩa, chưa có bằng chứng về edge: **NO STATISTICAL EDGE DETECTED**.

## Checkpoint Phase 7

Real Market Data Gateway chuẩn hóa provider → quality/store → snapshot/intelligence, hỗ trợ D1/H4/H1/M30/M15/M5 và chỉ dùng candle đã đóng. TradingView/calendar/institutional direct data giữ trạng thái unavailable khi chưa có nguồn hợp pháp. Institutional observations luôn phân biệt proxy. Paper execution là mô phỏng, không có broker route. Migration head Phase 7 là `20260825_0010`.

## Checkpoint Phase 8

Paper Trading Engine có account/equity, position state machine, cost-aware execution, sizing/risk/daily-loss gates, kill switch, bounded DCA, time-exit integration, causal replay, journal và performance. Chỉ setup `EXECUTABLE_SIMULATION` với dữ liệu/provider/model hợp lệ mới được entry. Migration head là `20260825_0011`; không có live order route.

## Checkpoint Phase 17

DEMO validation và shadow trading. Bốn lớp SHADOW / PAPER / DEMO / LIVE tách bạch nghiêm ngặt; LIVE **không tồn tại** chứ không phải bị tắt.

- `SHADOW` là mode thứ sáu và là simulation mode: chạy đúng pipeline DEMO rồi dừng trước lệnh broker. Nó không cần mở bất kỳ cổng broker nào vì không chạm broker.
- Shadow record được đúc từ `GateChainDecision` của chính đường DEMO, trong `propose()`. Không có cách nào tạo shadow record mà không có artefact DEMO đã dùng — parity theo cấu trúc, không phải theo quy ước.
- `DECISION_GATES` (10) và `TRANSMISSION_GATES` (2) được đặt tên trong `gates.py`. SHADOW/DEMO khớp trên mọi decision gate; `decision_approved` trả lời "lệnh có được vào không nếu execution đã mở".
- Mỗi ứng viên DEMO sinh một shadow record, kể cả khi bị chặn. `orders_sent = 0` được ghim ở dataclass, cột DB và payload API.
- So sánh chín khác biệt với tám phân loại. Entry lệch = execution, exit lệch = thị trường, side khác = signal chứ không phải fill. Tín hiệu DEMO không lấy vẫn được ghi qua `compare_unexecuted`.
- Bảy cửa sổ trượt chỉ tính ở nơi đủ dữ liệu; `WINDOW_NOT_COVERED` khi cửa sổ dài hơn lịch sử. Edge một cửa sổ = `UNSTABLE_EDGE`.
- Sàn mẫu: 100 signal, 20 thắng, 20 thua, 30 mỗi ô regime/session/timeframe. Quần thể toàn thắng vẫn trượt sàn vì không nói gì về downside.
- Tám performance gate fail-closed; `UNKNOWN` không phải `PASS`; `enables_execution` là hằng số False.
- `DEMO_AUTOMATION_ELIGIBLE` tính từ mười điều kiện, không bật gì. `DEMO_AUTOMATION_APPROVED=false` mặc định và không thay thế opt-in Phase 16.
- Circuit breaker mười một trigger, độc lập với kill switch, không tự đóng, không đóng vị thế. Recovery cần bốn mục và một người có tên; nhả breaker không nhả kill switch.
- Anomaly detector chín chiều so với baseline; không có baseline thì không có anomaly, chỉ có quan sát đầu tiên. Alert không dừng gì cả.
- Even-hour verdict mặc định `NOT_PROVEN`; DCA mặc định `NO_DCA` và bị `REJECTED_TAIL_RISK` khi win rate mua bằng tail risk.
- Migration head là `20260831_0020`; bảy bảng validation, không bảng nào có cột credential.
- Mặc định không đổi: `OBSERVATION`, LIVE và REAL account vẫn bất khả thi. Vẫn **NO STATISTICAL EDGE DETECTED**.

## Checkpoint Phase 16

Controlled MT5 DEMO trading. Toàn tuyến decision → risk → execution → reconciliation → learning đã chạy end-to-end trên tài khoản DEMO đã xác minh. **Không** live trading, **không** real-account execution.

- Mặc định không đổi: `DEMO_EXECUTION_MODE=OBSERVATION`, `LIVE_TRADING_ENABLED=false`, `REAL_ACCOUNT_EXECUTION=false`, `DEMO_TRADING_ENABLED=false`, `MT5_EXECUTION_ENABLED=false`, `EXECUTION_KILL_SWITCH=true`. `DEMO_AUTOMATED` cần thêm `DEMO_AUTOMATED_EXECUTION_ENABLED=true`, nên tự động hóa tốn hai cài đặt có chủ ý chứ không phải một.
- Năm mode tường minh, không chuyển ngầm. Mode sai chính tả bị `UnknownExecutionMode` từ chối lúc khởi động; một cổng đóng chặn *lệnh*, không hạ *mode*.
- `DemoGateChain` mười hai cổng, chạy hết, fail-closed, và trả về **mọi** lý do cùng lúc. Nó bọc chứ không thay `ExecutionGuard`: `MT5ExecutionClient` vẫn từ chối truyền nếu thiếu approval khớp request id.
- REAL account bị chặn bốn lớp độc lập: Settings, DemoAccountValidator, ExecutionGuard, và lần đọc lại account ngay trước khi truyền. UNKNOWN bị chặn ở mọi nơi REAL bị chặn.
- Position sizing suy ra từ equity × risk ÷ (stop_ticks × tick_value), rồi clamp theo max_position_size, volume_max, exposure room và margin, rồi floor theo volume_step. Thiếu stop / equity / tick economics → volume 0 kèm lý do. Ngân sách dưới một lot → `BELOW_MINIMUM_VOLUME`, không làm tròn lên.
- `execution_request_id` = sha256(signal | symbol | side | intent | strategy | trading_day). Lần gửi thứ hai bị chặn; một proposal bị cổng chặn chưa chạm broker nên gửi lại là lần đầu.
- DCA tắt mặc định; khi bật vẫn chạy lại toàn bộ chuỗi cổng, bị chặn bởi level / aggregate exposure / invalidation. Không martingale: volume của level sau nhỏ hơn level đầu vì stop xa hơn.
- Trading day có timezone và reset hour tường minh. Peak equity không reset theo ngày, nên total drawdown xuyên ngày; restore giữ nguyên ngân sách sau restart.
- Reconciliation mismatch → engage kill switch (safe shutdown). Emergency shutdown chặn lệnh mới, **không** đóng vị thế; `demo_emergency_events.positions_closed` luôn false.
- Checkpoint giờ chẵn đánh giá lại, không đóng theo đồng hồ. Ngược trend chịu ngưỡng confidence chặt hơn. Tám exit reason, đóng không lý do thì raise.
- NN advisory: có thể từ chối, không bao giờ vượt cổng. Chỉ CHAMPION được tự động thực thi.
- Sau khi lệnh đóng, outcome vào `observation_performance` với nhãn `DEMO_EXECUTION`; `retrained=false` là hằng số.
- Migration head là `20260830_0019`; sáu bảng `demo_*`, không bảng nào có cột credential.
- DEMO performance báo sample size kèm mọi con số và `reliable=false` dưới 30 lệnh đã đóng. Vẫn **NO STATISTICAL EDGE DETECTED**.

## Checkpoint Phase 15

AI research lab và champion/challenger cho chiến lược. So sánh khách quan trên forward observation; `orders_sent` luôn 0.

- `StrategyRegistry`: 6 trạng thái, `ALLOWED_TRANSITIONS` là bảng duy nhất, `REJECTED`/`RETIRED` terminal. `fingerprint` là hash nội dung nên đổi tên một chiến lược rồi thử lại không phải giả thuyết mới.
- Thăng hạng cần `ApprovalToken` (tên người + lý do). `transition(..., CHAMPION)` raise. Champion cũ tự động `RETIRED` với ghi chú `SUPERSEDED_BY`.
- 8 thí nghiệm là cấu hình; `experiment_id` là hash nội dung của 10 trường, **loại trừ timestamp** — chạy lại cùng cấu hình cho cùng id.
- Ablation 9 arm, 5 verdict. Mặc định `NOT_PROVEN`; `HARMFUL` được báo, không bị bỏ. `best_arm` chỉ chọn trong arm reliable.
- Ma trận regime/session/timeframe + nghiên cứu chuyển regime. Ô dưới ngưỡng vẫn in nhưng không tính là bằng chứng.
- DCA: `REJECTED_TAIL_RISK` khi win rate lên mà tail/drawdown xấu đi. Mặc định `NO_DCA`.
- Exit: 7 họ, so bằng `capture_ratio` (net thực hiện trên MFE có sẵn) chứ không chỉ win rate.
- NN value: mặc định `NN_VALUE_NOT_PROVEN`; mean tốt hơn kèm drawdown xấu hơn cũng là `NOT_PROVEN`.
- Significance: 4 hàng rào (mẫu, khoảng tin cậy, effect size, ổn định). Phương sai 0 → `EFFECT_SIZE_UNAVAILABLE`, không bao giờ significant.
- Multiple testing: Bonferroni + Benjamini-Hochberg, cảnh báo `BEST_OF_N` và lặp test. Holdout 20% đuôi gần nhất, budget 1 lần đọc.
- Liquidity event study: 7 loại, **không** tuyên bố hoạt động tổ chức — mọi lần xuất hiện của từ cấm phải nằm trong ngữ cảnh phủ định, kiểm bằng test.
- Signal weight: trọng số được **nghiên cứu**, không hard-code; tín hiệu thiếu mẫu nhận `None` chứ không nhận trọng số nhỏ. `applied: false`.
- 3 bảng mới; migration head là `20260829_0018`. `/research/*` và `/dashboard/research` đều read-only.
- Vẫn **NO STATISTICAL EDGE DETECTED**: chưa có dữ liệu forward thật.

## Checkpoint Phase 14

Vòng quan sát forward 24/7. Driver chạy lịch, giải quyết horizon, gán nhãn, nạp dataset, đo hiệu năng, phát hiện drift và đánh giá edge — end to end, `orders_sent` luôn 0.

- `ObservationDriver`: 5 interval hợp lệ (60/300/900/1800/3600s), mặc định 300. Interval ngoài danh sách bị raise, không làm tròn.
- `cycle_id` xác định: cùng symbol + timeframe + candle luôn cho cùng id, kể cả sau restart ở process khác. Chạy lại là DUPLICATE.
- Máy trạng thái 10 bước, tiến một bước một lần; 4 trạng thái lỗi terminal (`DATA_INVALID`, `MODEL_ERROR`, `CALCULATION_ERROR`, `TIMEOUT`).
- `ForwardOutcomeEngine` từ chối trả lời sớm: 5 lý do từ chối tường minh. Kết quả là **net** sau spread + commission + slippage + swap.
- `actual_direction` đọc từ chuyển động giá thô, không từ dấu của return đã ký hướng — nếu không, mọi SELL thắng bị coi là dự đoán sai.
- 11 lớp lỗi; `HIGH_CONFIDENCE_FAILURE` theo ngưỡng cấu hình (0.75), có index riêng trong DB.
- 5 cửa sổ trượt (7/14/30/60/90 ngày) và 3 chiều segment (regime/session/timeframe). Segment thua tiền là `FAILS`; cờ `overconfident` báo riêng để không che mất sự thật thứ hai.
- `EdgeDetector`: 4 verdict, 9 baseline bắt buộc, bằng chứng phải là `FORWARD_OBSERVATION`. `EvidenceRefused` chặn backtest theo tên.
- Training vẫn thủ công. `AI_AUTOMATIC_TRAINING` bị chặn lúc khởi động; không module nào trong `observation/` import được trainer.
- 6 bảng mới; migration head là `20260828_0017`. `/ai` và `/observation` **không có** write route mới.
- Vẫn **NO STATISTICAL EDGE DETECTED**: chưa có dữ liệu forward thật.

## Checkpoint Phase 13

Neural network learning và forward observation. Vòng `OBSERVE -> LABEL -> DATASET -> TRAIN -> VALIDATE -> COMPARE -> REGISTER` chạy end-to-end. Không có automated trading, không có demo execution, không có live trading.

- Dataset có version ba tầng (`features_v1` / `labels_v1` / `scaler_v1`); `dataset_id()` là hash nội dung, nên hai dataset khác nhau không thể lẫn.
- `LabelingEngine` từ chối gán nhãn khi horizon chưa trôi qua hoặc dữ liệu chưa chạm deadline. Lý do từ chối được đếm trong `DatasetAudit`.
- `DatasetQualityChecker` chặn sáu lớp leakage. Scaler chỉ fit trên TRAIN; guard là `MINIMUM_DEVIATION = 1e-12`, không phải `std or 1.0`, vì feature hằng số cho std cỡ `1e-18`.
- `random_split()` tồn tại chỉ để luôn raise `RandomSplitRefused`. `WalkForwardWindow` mang timestamp, không phải chỉ số mảng.
- `MultiTaskMLP`: direction softmax + expected return/MFE/MAE + volatility, trên 141 feature. `_check_scaling()` ghi cảnh báo khi đầu vào có vẻ chưa scale.
- 8 rule baseline. Hoà với baseline vẫn là không vượt baseline. Verdict lợi thế có ba giá trị và `INSUFFICIENT_DATA` là kết quả đúng.
- `ModelRegistry` sáu trạng thái với `ALLOWED_TRANSITIONS`; 10 tiêu chí champion/challenger đều là out-of-sample. `promote()` cần `ApprovalToken`.
- Drift `FLAG_ONLY`. `RetrainingRequest` có `auto_trains: False`, `auto_promotes: False`.
- Namespace `/ai` chỉ có hai endpoint ghi: `POST /ai/retraining/request` và `POST /ai/models/{model_id}/approve`. Không endpoint nào train model.
- Migration head là `20260827_0016`. Vẫn **NO STATISTICAL EDGE DETECTED**.

## Checkpoint Phase 12

Live market validation và observation mode. Toàn bộ pipeline MT5 → data → D1/H4/H1/M30/M15/M5 → quality gate → indicators → structure → liquidity → regime → NN → strategy → risk → **execution simulation** → dashboard → monitoring → alerting đã chạy end-to-end. Không có automated trading, không có live trading.

- `OBSERVATION_MODE=true` mặc định: mọi tín hiệu được tính, `orders_sent` luôn bằng 0. Đây là lớp chặn ngoài cùng, thắng cả khi mọi cổng Phase 11 đều mở.
- `DemoAccountValidator` bốn trạng thái; chỉ `VALID_DEMO` đi tiếp. REAL account có ưu tiên báo cáo cao nhất, kể cả khi terminal đã ngắt kết nối.
- `DataQualityGate` chặn future timestamp, duplicate, out-of-order, broken OHLC, giá ≤ 0, thiếu lịch sử, stale, naive timestamp. FAIL ở bất kỳ timeframe nào → **không sinh tín hiệu**. Gap rời rạc chỉ là WARN vì thị trường thật có gap cuối tuần.
- Unified regime sáu trạng thái với quyền quyết định thuộc D1/H4/H1; M5 một mình luôn cho `UNKNOWN`.
- Liquidity tách OBSERVED khỏi INFERRED, dùng ngôn ngữ xác suất, và không bao giờ khẳng định một tổ chức cụ thể ở một mức giá.
- DCA projection luôn có maximum theoretical loss và điều kiện invalidation; ladder không bao giờ unbounded. Time-exit dùng even-hour checkpoint và đánh dấu COUNTER_TREND với ngưỡng confidence chặt hơn. Cả hai chỉ phân tích, không thực thi.
- Migration head là `20260827_0015`; 6 bảng observation, không bảng nào có cột credential.
- `observation_performance` là forward observation, **không phải backtest** và không phải kết quả đã thực hiện. Vẫn **NO STATISTICAL EDGE DETECTED**.

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
