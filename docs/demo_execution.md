# DEMO Execution (Phase 11)

Phase 11 xây **nền tảng execution** và **một manual DEMO test**. Không có automated trading, không có strategy auto execution, không có live trading.

## Ba cổng độc lập

Một lệnh chỉ đi được khi **tất cả** đều mở, và cả ba đều đóng theo mặc định:

| Cổng | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `DEMO_TRADING_ENABLED` | `false` | cho phép giao dịch DEMO |
| `MT5_EXECUTION_ENABLED` | `false` | cho phép MT5 nhận lệnh |
| `EXECUTION_KILL_SWITCH` | `true` (engaged) | phải được nhả |

Ngoài ra `MT5_READ_ONLY` phải là `false`, `TRADING_ENVIRONMENT` phải là `DEMO`, và `LIVE_TRADING_ENABLED` **vẫn raise ngay khi khởi động** nếu bật.

Account phải là DEMO/CONTEST thật, và tên server phải khớp mẫu DEMO (`demo`, `trial`, `practice`, `test`). Account `REAL` bị chặn hai lần: ở guard, và một lần nữa ngay trước khi truyền.

## Thay đổi so với Phase 10

Phase 10 để `Settings` raise khi `DEMO_TRADING_ENABLED=true` hoặc `MT5_READ_ONLY=false`. Nếu giữ nguyên, endpoint manual test sẽ không bao giờ chạy được. Phase 11 chuyển ba cờ này từ **startup invariant** sang **execution gate**, được `ExecutionGuard` kiểm tra lại trên **từng lệnh**.

`LIVE_TRADING_ENABLED`, `TRADING_ENVIRONMENT` và `READ_ONLY_MODE` vẫn là startup invariant và vẫn raise.

Đọc market data **không** còn phụ thuộc `mt5_read_only`: bật execution không làm hỏng dữ liệu.

## Luồng

```
OrderRequest
   ↓ REQUEST        ghi audit
ExecutionGuard      12 nhóm kiểm tra
   ↓ VALIDATION     ghi audit (kèm từng check pass/fail)
   ↓ DECISION       ghi audit
MT5ExecutionClient  yêu cầu approval khớp request_id; đọc lại account
   ↓ EXECUTION      ghi audit
OrderResult
   ↓ RESULT         ghi audit + execution_results
Reconciler          so request / result / position
   ↓ RECONCILIATION ghi audit + reconciliation_records
```

Lệnh bị từ chối cũng đi qua REQUEST → VALIDATION → DECISION → RESULT, nên một từ chối được audit đầy đủ như một lệnh khớp.

## Endpoint

```text
POST /execution/demo/test        gửi MỘT lệnh DEMO thủ công
GET  /execution/status           trạng thái, gates, last order, reconciliation
GET  /execution/orders           lịch sử kết quả
GET  /execution/audit            audit trail (lọc theo request_id)
GET  /execution/kill-switch      trạng thái + lịch sử kill switch
POST /execution/kill-switch/engage   chặn
POST /execution/kill-switch/release  nhả (bắt buộc có lý do)
GET  /dashboard/execution        khối dashboard
```

Payload manual test **không có** `strategy_id`, nên strategy không thể lái endpoint này.

Ví dụ (dưới cấu hình mặc định sẽ bị từ chối, đúng như thiết kế):

```bash
curl -X POST localhost:8000/execution/demo/test \
  -H 'Content-Type: application/json' \
  -d '{"symbol":"EURUSD","side":"BUY","volume":0.01,"sl":1.09,"tp":1.11}'
```

## Giới hạn

`config/settings.yaml` → `phase_11`: volume 0.01–0.10, tối đa 3 position, 3 DCA, spread ≤ 0.0005, daily drawdown ≤ 3%, khoảng cách stop tối thiểu 0.0005.

## Bật thủ công để test

Chỉ làm trên tài khoản DEMO đã xác minh:

```
MT5_READ_ONLY=false
DEMO_TRADING_ENABLED=true
MT5_EXECUTION_ENABLED=true
EXECUTION_KILL_SWITCH=false
```

Sau khi test xong, đặt lại `EXECUTION_KILL_SWITCH=true`.
