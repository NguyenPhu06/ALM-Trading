# ALM-Trading

## Phase 17 — DEMO Validation & Shadow Trading

Phase 17 trả lời một câu hỏi: **Champion Strategy và Neural Network hiện tại có tạo ra forward performance ổn định sau chi phí thực thi thật hay không?** Câu trả lời trung thực dự kiến là `INSUFFICIENT_DATA` trong một thời gian dài, và mọi thứ ở phase này được xây để nó nói đúng như vậy chứ không phải điều gì dễ nghe hơn.

Bốn lớp tách bạch: **SHADOW** (không gửi lệnh, chi phí mô hình hoá) · **PAPER** (không gửi lệnh, chi phí mô phỏng) · **DEMO** (gửi lệnh có cổng, chi phí thật) · **LIVE** (**không tồn tại**). `LIVE_TRADING_ENABLED=true` và `REAL_ACCOUNT_EXECUTION=true` đều bị validator từ chối lúc khởi động, và repo không có adapter live nào.

SHADOW **không phải pipeline thứ hai**. Bản ghi shadow được đúc từ chính `GateChainDecision` mà đường DEMO vừa tạo ra, trên cùng một code path — nên hai bên không thể trôi khỏi nhau. `ShadowRecorder` không cầm client, guard, connection hay gate chain nào; test parse module để chứng minh điều đó.

Mười hai cổng tách làm hai nhóm, và sự tách này được đặt tên trong code. `DECISION_GATES` (account, data quality, spread, risk, drawdown, exposure, DCA, strategy, model, session) trả lời "đây có phải lệnh đáng vào không" — SHADOW và DEMO **phải khớp**. `TRANSMISSION_GATES` (ExecutionGuard, KillSwitch) trả lời "có được gửi tới broker không" — và khác biệt đó **chính là** mode. Vì vậy mỗi shadow signal mang hai verdict: `approved` (lệnh có được gửi không — trong SHADOW luôn false) và `decision_approved` (lệnh có được **vào** không nếu execution đã mở).

Mọi ứng viên DEMO — được duyệt, bị chặn, hay đang chờ người duyệt — đều sinh một bản ghi shadow. Nhóm bị chặn mới là nhóm đáng giá nhất: đó chính xác là quần thể mà các cổng đã loại, và việc loại nó có giúp ích hay không là câu hỏi performance gate chỉ trả lời được nếu các dòng đó tồn tại. `orders_sent` là hằng số 0 trong dataclass, trong cột database, và trong payload API.

So sánh SHADOW/DEMO đo **chín** khác biệt và phân loại từng cái: `NONE`, `SIGNAL_ERROR`, `EXECUTION_ERROR`, `MARKET_MOVEMENT`, `SPREAD_ERROR`, `SLIPPAGE_ERROR`, `COST_ERROR`, `TIMING_ERROR`. Hai phân biệt quan trọng nhất: **entry lệch là execution, exit lệch là thị trường**; và **side khác không phải lỗi thực thi** — đó là một lệnh khác, và nó chỉ về signal chứ không phải fill.

Bảy cửa sổ trượt 24h/3d/7d/14d/30d/60d/90d chỉ được tính **ở nơi có đủ dữ liệu**. Một cửa sổ dài hơn lịch sử hiện có báo `WINDOW_NOT_COVERED` và `INSUFFICIENT_DATA` thay vì một con số: figure 90 ngày tính từ bốn ngày giao dịch không phải figure 90 ngày. Edge ở một cửa sổ mà không ở các cửa sổ khác là `UNSTABLE_EDGE`, không phải edge.

Tám performance gate, và tính chất quyết định được thực thi trong code: **gate trượt không bao giờ mở đường cho execution rủi ro hơn**. `enables_execution` là hằng số False, và evaluator không có method nào ghi setting. Gate không đo được là `UNKNOWN` — không phải PASS.

`DEMO_AUTOMATION_ELIGIBLE` được **tính** từ mười điều kiện cộng gate report, fail-closed trên mọi trục. Đủ điều kiện **không bật gì cả**: `enabled` và `automatically_enabled` đều là hằng số False, và `DEMO_AUTOMATED` vẫn cần opt-in riêng của Phase 16. `DEMO_AUTOMATION_APPROVED` chỉ ghi nhận việc một người thật đã chấp nhận kết luận, và một cấu hình approve automation mà chưa arm bị từ chối lúc khởi động thay vì âm thầm coi như đã arm.

Circuit breaker mười một điều kiện, tách khỏi kill switch **có chủ ý**: nó sống sót qua việc operator nhả switch, nên phục hồi không thể là một cú bấm nút. Section 23 đòi bốn thứ — health check, risk check, account validation, và một con người có tên kèm lý do — và không có timeout, không có retry counter, nên `DEMO_AUTOMATED` không thể tự khởi động lại bằng cách chờ. Nhả breaker cũng **không** nhả kill switch: hai cơ chế, hai hành động có chủ ý.

Even-hour checkpoint ghi đủ trend, liquidity, structure, Ichimoku, RSI, ADX, NN, strategy, risk, position state, decision và reason — thiếu bất kỳ mục nào thì bị đánh dấu **incomplete** chứ không lặng lẽ chấm điểm. Rồi câu hỏi khó hơn: những quyết định đó có cải thiện kết quả không? Mặc định là `NOT_PROVEN`, đúng như spec yêu cầu "Do not assume they do".

DCA vẫn tắt mặc định. Nếu có quần thể DCA, nó được đo **từng level một** và so với NO_DCA, với quy tắc quyết định thực thi đúng nguyên văn: **từ chối DCA nếu win rate tăng chỉ nhờ tail risk tăng đáng kể**. `tail_loss` là trung bình 5% kết quả tệ nhất — con số mà DCA giấu đi.

```bash
alembic upgrade head    # 20260831_0020: bảy bảng validation
python -m pytest -q
```

Tài liệu: [shadow trading](docs/shadow_trading.md), [demo validation](docs/demo_validation.md), [shadow vs demo](docs/shadow_vs_demo.md), [execution quality](docs/execution_quality.md), [performance gates](docs/performance_gates.md), [circuit breaker](docs/circuit_breaker.md), [demo operations](docs/demo_operations.md).

## Phase 16 — Controlled MT5 DEMO Trading

Phase 16 mở một đường thực thi **chỉ trên tài khoản MT5 DEMO đã xác minh**. LIVE trading vẫn là không thể: `LIVE_TRADING_ENABLED=true` và `REAL_ACCOUNT_EXECUTION=true` đều bị validator từ chối lúc khởi động, và không có adapter live nào tồn tại trong repo.

Mặc định sau Phase 16 **không đổi**: `DEMO_EXECUTION_MODE=OBSERVATION`, `DEMO_TRADING_ENABLED=false`, `MT5_EXECUTION_ENABLED=false`, `EXECUTION_KILL_SWITCH=true` (engaged), `DEMO_AUTOMATED_EXECUTION_ENABLED=false`, `DEMO_DCA_ENABLED=false`. Chạm được tới broker cần đổi năm cờ một cách có chủ ý, nối một tài khoản DEMO đã xác minh, và qua **mười hai cổng** cho từng lệnh.

Năm mode được khai báo tường minh: `OBSERVATION`, `PAPER`, `DEMO_MANUAL_APPROVAL`, `DEMO_AUTOMATED`, `LIVE_DISABLED`. **Không có chuyển mode ngầm** — một cổng đóng chặn *lệnh*, không bao giờ hạ *mode*. Một mode string sai chính tả bị từ chối lúc khởi động thay vì rơi về mặc định.

`DEMO_MANUAL_APPROVAL` là mode để chạy toàn tuyến với một con người ở giữa: `Signal → Risk → Proposal → Human Approval → ExecutionGuard → MT5 DEMO`. Một approval mang tên người thật, có lý do, và **hết hạn** — approval cho sau khi thị trường đã đi không còn là approval hiện tại.

Không có lot size tùy tiện ở bất kỳ đâu. Volume được suy ra từ equity, risk %, stop distance và tick economics của symbol, rồi bị chặn bởi ràng buộc volume của broker và giới hạn exposure. Thiếu stop, thiếu equity hay thiếu tick value đều trả về volume 0 kèm lý do, không phải một giá trị mặc định. Ngân sách rủi ro không mua nổi một lot thì **từ chối**, vì giao dịch lot tối thiểu vẫn sẽ vượt risk đã cấu hình.

Idempotency là `sha256(signal | symbol | side | intent | strategy | trading_day)`: cùng một quyết định luôn cho cùng một `request_id`, nên lần gửi thứ hai bị **nhận diện**, không chỉ là khó xảy ra. Một proposal bị cổng chặn thì chưa từng chạm broker, nên gửi lại sau khi sửa cổng là lần đầu tiên chứ không phải trùng lặp.

DCA tắt mặc định. Khi bật, **mọi** lệnh DCA chạy lại toàn bộ chuỗi cổng — không phải một phiên bản rút gọn — và bị chặn bởi số level, aggregate exposure và điều kiện invalidation. Không có martingale ở bất kỳ đâu: size đến từ sizer, và vì trung bình giá đẩy stop ra xa entry mới nên volume của level sau **nhỏ hơn** level đầu.

Reconciliation so request / result / position và chỉ báo cáo, không bao giờ sửa. Một mismatch là **safe shutdown**: kill switch được engage nên không lệnh mới nào đi tiếp khi trạng thái nội bộ và trạng thái broker còn bất đồng. Emergency shutdown chặn lệnh mới và **không** đóng vị thế đang mở — thanh lý là một quyết định thứ hai, lớn hơn, do chính đoạn code vừa phát hiện nó không tin được input của mình.

Checkpoint giờ chẵn là lúc **đánh giá lại** vị thế, không phải lúc đóng. Đồng hồ đổi không phải là lý do để đứng ngoài; tại checkpoint hệ thống chạy exit policy đã cấu hình và một vị thế ngược trend chịu ngưỡng confidence chặt hơn. Mọi lần thoát đều ghi lý do — tám lý do được khai báo, đóng mà không có lý do thì raise.

NN vẫn là advisory. Nó có thể **từ chối** (model failed, confidence dưới ngưỡng), nhưng không bao giờ vượt qua được RiskGate, StrategyGate hay ExecutionGuard. Chỉ Champion Strategy được tự động thực thi.

Sau khi một lệnh DEMO đóng, kết quả được gửi vào observation/performance pipeline và gắn nhãn `DEMO_EXECUTION`. Chỉ vậy thôi: `retrained` là hằng số `false` trên mọi record, và `AI_ONLINE_LEARNING_ENABLED` / `AI_AUTOMATIC_TRAINING` vẫn bị từ chối lúc khởi động.

```bash
alembic upgrade head    # 20260830_0019: sáu bảng demo_*
python -m pytest -q
```

Tài liệu: [controlled demo trading](docs/controlled_demo_trading.md), [demo execution safety](docs/demo_execution_safety.md), [demo risk limits](docs/demo_risk_limits.md), [demo reconciliation](docs/demo_reconciliation.md), [demo trade journal](docs/demo_trade_journal.md), [demo operations](docs/demo_operations.md).

## Phase 15 — AI Research Lab & Champion/Challenger

Phase 15 là khung nghiên cứu so sánh chiến lược, tổ hợp feature và model một cách khách quan — **chỉ trên forward observation**, không bao giờ trên backtest.

`StrategyRegistry` lưu bản khai báo luật (features, timeframes, entry/exit/DCA/risk) và sáu trạng thái `EXPERIMENTAL → TESTING → VALIDATED → CHAMPION → RETIRED`, cộng `REJECTED`. `CHAMPION` **không** đến bằng transition: `transition(..., CHAMPION)` raise, và `promote()` đòi một `ApprovalToken` mang tên người thật.

Tám thí nghiệm là **cấu hình, không phải code** (smc, ichimoku, rsi, adx, indicators, smc+indicators, smc+nn, tất cả). Ablation chín arm đo đóng góp gia tăng của từng thành phần — và mặc định là **không cải thiện**: một delta dương không tách được khỏi nhiễu được báo `NOT_PROVEN`, một thành phần làm xấu đi được báo `HARMFUL`.

Ma trận regime / session / timeframe: mỗi ô có sample size riêng và cờ `reliable`. Ô dưới ngưỡng vẫn được in, nhưng không bao giờ được tính là bằng chứng. Một chiến lược có lãi tổng thể vẫn có thể lỗ ở BEAR, và test khẳng định điều đó.

DCA **không được mặc định là có lợi**: một cấu hình nâng win rate nhưng làm xấu tail risk hoặc drawdown bị `REJECTED_TAIL_RISK`, và `recommended` mặc định là `NO_DCA`. NN cũng vậy — verdict mặc định là `NN_VALUE_NOT_PROVEN`, và NN không bị ép vào chiến lược.

`ExperimentLedger` đếm mọi giả thuyết và nâng hàng rào theo số lần thử: 20 lần ở alpha 0.05 nâng ngưỡng lên 0.0025, nên một p-value 0.04 "may mắn" không sống sót. `HoldoutGuard` giữ 20% gần nhất, cho đọc **một lần**, và đánh dấu kết quả không còn valid nếu bị đọc lần thứ hai.

Không module nào trong `research/` cầm execution client, import `execution.*`/`paper.*`, hay ghi vào một setting — kiểm bằng cách parse mọi module. Mặc định an toàn không đổi.

```bash
python -m scripts.run_research_lab --days 180 --dry-run
```

Tài liệu: [AI research lab](docs/ai_research_lab.md), [strategy registry](docs/strategy_registry.md), [ablation study](docs/ablation_study.md), [strategy comparison](docs/strategy_comparison.md), [statistical significance](docs/statistical_significance.md), [multiple testing](docs/multiple_testing.md), [champion/challenger](docs/champion_challenger.md).

## Phase 14 — 24/7 Forward Observation & AI Learning Loop

Phase 14 biến vòng học Phase 13 thành một hệ thống chạy liên tục. `ObservationDriver` giữ cho cycle nổ đúng lịch (60/300/900/1800/3600 giây, mặc định **5 phút**), giải quyết observation khi horizon trôi qua, và sống sót qua restart mà không nhân đôi gì.

Idempotency là `sha256(symbol | timeframe | candle_timestamp)`: cùng một cây nến, trong process khác hay múi giờ khác, luôn cho cùng một `cycle_id`. Chạy lại là **DUPLICATE**, không phải observation thứ hai.

Mỗi observation đi qua một máy trạng thái mười bước, tiến **một bước một lần** — `CREATED → … → OBSERVING → HORIZON_REACHED → OUTCOME_CALCULATED → LABELED → DATASET_READY` — với bốn trạng thái lỗi terminal. Kết quả chỉ được tính **sau khi** horizon thực sự trôi qua, và mọi con số hiệu năng là **net** sau spread, commission, slippage và swap: một chuyển động gộp dương nhỏ hơn chi phí là một khoản lỗ.

Sai lầm được phân loại thành 11 lớp, và `HIGH_CONFIDENCE_FAILURE` được theo riêng — model sai lúc tự tin nguy hiểm hơn model kém nhưng thành thật. Hiệu năng được cắt theo 5 cửa sổ trượt (7/14/30/60/90 ngày) và ba chiều: regime, session, timeframe. Một model tốt trên M5 chưa nói gì về H1.

`EdgeDetector` cho bốn verdict — `EDGE_DETECTED`, `UNSTABLE_EDGE`, `NO_EDGE`, `INSUFFICIENT_DATA` — và phải vượt **9 baseline**. PnL dương một mình không bao giờ là edge. Bằng chứng phải là forward observation: truyền backtest vào sẽ bị từ chối theo tên.

Training vẫn là job thủ công. `AI_AUTOMATIC_TRAINING=false` bị validator chặn lúc khởi động, và driver không import được bất kỳ trainer nào — điều đó được chứng minh bằng cách parse import graph, không phải bằng hy vọng.

Mặc định an toàn không đổi: `LIVE_TRADING_ENABLED=false`, `DEMO_TRADING_ENABLED=false`, `MT5_EXECUTION_ENABLED=false`, `EXECUTION_KILL_SWITCH=true`, `OBSERVATION_MODE=true`. Driver **từ chối khởi động** nếu bất kỳ cổng nào trong số đó mở.

```bash
python -m scripts.run_observation_driver --ticks 1 --dry-run
```

Tài liệu: [observation driver](docs/observation_driver.md), [forward learning](docs/forward_learning.md), [model error analysis](docs/model_error_analysis.md), [statistical edge](docs/statistical_edge.md), [AI training operations](docs/ai_training_operations.md), [model drift](docs/model_drift.md).

## Phase 13 — Neural Network Learning & Forward Observation

Phase 13 dựng vòng học **forward-only**: `OBSERVE -> LABEL -> DATASET -> TRAIN -> VALIDATE -> COMPARE -> REGISTER`. Đây **không** phải `OBSERVE -> TRAIN -> TRADE` — không bước nào trong chuỗi gửi order.

Dataset có ba version độc lập (`features_v1`, `labels_v1`, `scaler_v1`) và một dataset id là hash nội dung. Nhãn chỉ được tạo **sau khi** horizon thực sự trôi qua; nếu tương lai chưa tồn tại, engine từ chối gán nhãn thay vì đoán. Nhãn có tính chi phí giao dịch: chuyển động nhỏ hơn spread + commission là `NEUTRAL`, không phải cơ hội. Split luôn theo thời gian — `random_split()` tồn tại chỉ để **luôn** raise.

`MultiTaskMLP` học đồng thời hướng đi (softmax ba lớp), expected return, expected MFE, expected MAE và volatility từ 141 feature. Model được so với **8 baseline** theo luật; hoà với baseline tính là không vượt baseline. Kết luận về lợi thế có ba giá trị, và `INSUFFICIENT_DATA` là một câu trả lời đúng.

Model không bao giờ tự thăng hạng. `AI_AUTO_PROMOTE=false` và `AI_ONLINE_LEARNING_ENABLED=false` được validator ép cứng lúc khởi động — bật lên thì process không chạy. Promotion cần `ApprovalToken` của người thật qua `POST /ai/models/{model_id}/approve`. Drift chỉ `FLAG_ONLY`: nó cảnh báo, không retrain, không hạ champion, không chạm cờ execution.

Mặc định an toàn không đổi: `LIVE_TRADING_ENABLED=false`, `DEMO_TRADING_ENABLED=false`, `MT5_EXECUTION_ENABLED=false`, `EXECUTION_KILL_SWITCH=true`, `OBSERVATION_MODE=true`.

Tài liệu: [AI learning](docs/ai_learning.md), [dataset pipeline](docs/dataset_pipeline.md), [labeling](docs/labeling.md), [walk-forward validation](docs/walk_forward_validation.md), [champion/challenger](docs/champion_challenger.md), [model drift](docs/model_drift.md), [AI explainability](docs/ai_explainability.md), [model registry](docs/model_registry.md), [neural network](docs/neural_network.md).

## Phase 12 — Live Market Validation & Observation Mode

Phase 12 xác nhận toàn bộ pipeline chạy đúng trên MT5 thật với tài khoản DEMO: market data D1→M5, data quality gate, market structure, liquidity, indicators, multi-timeframe regime, neural network, strategy, risk — và kết thúc ở **execution simulation**, không phải execution.

`OBSERVATION_MODE=true` là mặc định: hệ thống quan sát thị trường thật, tính mọi tín hiệu, vị thế giả định, DCA giả định và PnL giả định, nhưng **gửi ZERO lệnh**. Đây là lớp bảo vệ ngoài cùng — ngay cả khi mọi cổng Phase 11 đều mở, execution vẫn bị chặn với `REASON = OBSERVATION_MODE_ACTIVE`.

`DemoAccountValidator` cho bốn kết quả tường minh (`VALID_DEMO`, `INVALID_ACCOUNT`, `UNKNOWN_ACCOUNT`, `CONNECTION_ERROR`); chỉ `VALID_DEMO` đi tiếp, và UNKNOWN không bao giờ được coi là an toàn. Market regime giữ quyền quyết định ở D1/H4/H1 — M5 một mình không bao giờ đặt được regime. Liquidity tách rõ **OBSERVED** khỏi **INFERRED** và không bao giờ khẳng định một tổ chức cụ thể đang ở một mức giá.

Mặc định an toàn cuối phase: `LIVE_TRADING_ENABLED=false`, `DEMO_TRADING_ENABLED=false`, `MT5_EXECUTION_ENABLED=false`, `EXECUTION_KILL_SWITCH=true`, `OBSERVATION_MODE=true`. Không có automated trading.

Tài liệu: [live market validation](docs/live_market_validation.md), [observation mode](docs/observation_mode.md), [MT5 demo validation](docs/mt5_demo_validation.md), [market snapshot](docs/market_snapshot.md), [neural network inference](docs/neural_network_inference.md).

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
