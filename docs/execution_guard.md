# Execution Guard

`ExecutionGuard` là **cổng bắt buộc** duy nhất có quyền phê duyệt một lệnh.

## Không thể bỏ qua

`MT5ExecutionClient.send_market_order()` yêu cầu một `GuardDecision` khớp đúng `request_id`. Nó từ chối:

- không có approval → `ExecutionTransportError: an ExecutionGuard approval is required`
- approval bị guard từ chối → `guard refused: ...`
- approval của request khác (replay) → `guard approval does not match this request`

Nghĩa là bỏ qua guard **không phải chuyện quy ước — nó không hoạt động**.

Ngay trước khi truyền, client còn đọc lại account một lần nữa; nếu là `REAL`, lệnh bị chặn dù đã có approval hợp lệ.

## Kiến trúc

```
Strategy  →  Risk Engine  →  ExecutionGuard  →  MT5ExecutionClient  →  Exness DEMO
                                  ▲
                          chỉ nơi này phê duyệt
```

Phase 11: Strategy **không** tự động đi qua đường này. Chỉ manual test.

## 12 nhóm kiểm tra

| Nhóm | Nội dung |
| --- | --- |
| `environment` | DEMO, không LIVE, DEMO_TRADING_ENABLED, MT5_EXECUTION_ENABLED, không read-only |
| `kill_switch` | kill switch phải được nhả |
| `connection` | terminal đang kết nối |
| `account` | không phải REAL, server khớp mẫu DEMO |
| `symbol` | symbol hợp lệ, nằm trong allowlist nếu có |
| `volume` | > 0, trong [min, max], đúng bước lot |
| `price` | > 0, quote hợp lệ, không lệch quá ngưỡng |
| `spread` | không vượt `max_spread` |
| `stops` | SL/TP đúng phía, đủ xa entry |
| `risk` | risk state, daily drawdown, exposure, position limit, DCA limit |
| `session` | phiên nằm trong allowlist |
| `strategy` | lệnh từ strategy cần `EXECUTABLE_SIMULATION` |

Guard **fail-closed**: thiếu account, thiếu quote, chưa kết nối đều là lý do từ chối, không phải lý do bỏ qua.

Mọi lý do đều được trả về cùng lúc, không dừng ở lỗi đầu tiên, nên audit trail cho thấy toàn bộ bức tranh.

## Kết quả

`GuardDecision(approved, request_id, reasons, checks)` — `checks` ghi từng nhóm pass/fail để dashboard và audit đọc được.
