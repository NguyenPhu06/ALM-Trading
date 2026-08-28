# Live Market Validation (Phase 12)

Phase 12 xác nhận toàn bộ pipeline chạy đúng trên MT5 thật với tài khoản DEMO, và **không bật giao dịch tự động**.

## Pipeline được xác nhận

```
MT5 → market data → D1 → H4 → H1 → M30 → M15 → M5 → data quality
   → indicators → market structure → liquidity → multi-timeframe regime
   → neural network → strategy → risk engine → EXECUTION SIMULATION
   → dashboard → monitoring → alerting
```

Tầng cuối là **simulation**, không phải execution. `ObservationCycle` không import `MT5ExecutionClient`, `DemoExecutionService` hay `PaperTradingService`; test AST khẳng định điều đó.

## Thứ tự chặn

Cycle dừng ở stage đầu tiên không đạt, và mỗi lần dừng đều được ghi lại:

| Stage | Dừng khi |
| --- | --- |
| `ACCOUNT` | account REAL, account unknown, server không xác minh, terminal không có, chưa kết nối |
| `MARKET_DATA` | không đọc được nến cho bất kỳ timeframe nào |
| `DATA_QUALITY` | bất kỳ timeframe nào FAIL gate → **không sinh tín hiệu** |
| `COMPLETED` | chạy hết; kết quả luôn là một simulation |

## Data quality gate

FAIL (loại cả batch): future timestamp, duplicate, out-of-order, broken OHLC, giá ≤ 0, thiếu lịch sử, stale, naive timestamp, không có dữ liệu.

WARN (vẫn phân tích): thiếu nến rời rạc — thị trường thật có gap cuối tuần và ngày lễ, nên gap không được dừng phân tích.

## Market regime

Sáu trạng thái: `STRONG_BULL`, `BULL`, `RANGE`, `BEAR`, `STRONG_BEAR`, `UNKNOWN`.

Quy tắc quan trọng nhất: **D1/H4/H1 giữ quyền quyết định hướng**. M30/M15/M5 chỉ tinh chỉnh độ mạnh và có thể tạo `conflict`, nhưng nếu không có bằng chứng từ khung cao thì regime là `UNKNOWN` — kể cả khi cả ba khung thấp đồng thuận. Enforce bằng cấu trúc, không phải bằng quy ước.

## Liquidity: OBSERVED vs INFERRED

- **OBSERVED** — tính được từ nến: equal high/low, previous day high/low, session high/low, sweep, displacement, rejection.
- **INFERRED** — giả thuyết suy ra: liquidity pool, resting order cluster.

Ngôn ngữ luôn có hedge theo mức confidence (`may indicate` / `is consistent with` / `strongly suggests`) và luôn kèm câu "this is an inference, not a confirmed order".

Hệ thống **không bao giờ** khẳng định một ngân hàng, tổ chức, cá voi hay market maker đang ở một mức giá. `contains_forbidden_claim()` và test tương ứng canh gác điều này.

## Execution simulation

Mỗi strategy decision sinh một bản ghi:

```
SIGNAL = BUY
RISK = APPROVED
EXECUTION = BLOCKED
REASON = OBSERVATION_MODE_ACTIVE
```

`orders_sent` luôn bằng 0.

## Logging mỗi cycle

`cycle_id`, timestamp, symbol, timeframes, data_quality, regime, liquidity, indicators, NN output, strategy, risk, execution decision, execution block reason. Không log secret.

## Trạng thái an toàn cuối phase

```
TRADING_ENVIRONMENT=DEMO
LIVE_TRADING_ENABLED=false
DEMO_TRADING_ENABLED=false
MT5_EXECUTION_ENABLED=false
EXECUTION_KILL_SWITCH=true
OBSERVATION_MODE=true
```

Không có automated order submission trong phase này.
