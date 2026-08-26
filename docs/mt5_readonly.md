# MT5 Read-Only Integration (Phase 10)

MetaTrader 5 trong Phase 10 là **DATA PROVIDER**, không phải execution provider. Không có bất kỳ đường dẫn nào gửi lệnh, sửa lệnh, đóng lệnh hay đặt SL/TP thật.

## Safety lock

Kết nối và mọi thao tác đọc đều đi qua `MT5SafetyLock`. Cấu hình bắt buộc:

| Biến | Giá trị bắt buộc |
| --- | --- |
| `TRADING_ENVIRONMENT` | `DEMO` |
| `LIVE_TRADING_ENABLED` | `false` |
| `DEMO_TRADING_ENABLED` | `false` |
| `MT5_READ_ONLY` | `true` |
| `MT5_EXECUTION_ENABLED` | `false` |
| `READ_ONLY_MODE` | `true` |

Sai bất kỳ giá trị nào:

- trước khi kết nối → `BLOCK_CONNECTION` (terminal không được `initialize`)
- trước khi đọc dữ liệu → `BLOCK_DATA_ACCESS`

Lock **không bao giờ tự sửa cấu hình** để vượt qua chính nó. `Settings` cũng từ chối khởi tạo với cờ sai, nên đây là hai lớp phòng vệ độc lập.

## Read-only enforcement

`MT5ReadOnlyClient` **không định nghĩa** `send_order`, `modify_order`, `close_position`, `open_position` hay `place_dca` — `hasattr(client, "send_order")` là `False`.

Nếu một adapter cần interface chung, dùng `ReadOnlyExecutionGuard`: mọi method raise `ReadOnlyModeError`. `MT5ReadOnlyClient` cố ý **không** kế thừa class này.

`test_mt5_cannot_execute_trade()` kiểm tra điều này, và một test khác parse AST toàn bộ package để chắc chắn không có lời gọi `order_send`/`order_check`/`position_close` nào.

## Interface

```python
client = MT5ReadOnlyClient()
client.connect()          # ConnectionReport
client.is_connected()
client.get_account()      # ReadResult[MT5Account]
client.get_symbols()
client.get_symbol_info("EURUSD")
client.get_tick("EURUSD")
client.get_rates("EURUSD", "M15", 500)
client.get_multi_timeframe_rates("EURUSD")   # D1 → M5
client.get_positions()
client.get_orders()
client.get_history()
client.health_check()     # HealthReport
client.disconnect()
```

Mọi read trả `ReadResult(ok, data, code, reasons)` nên caller không phải phân biệt "rỗng" với "không khả dụng".

## Account validation

Sau khi kết nối, account được đọc và phân loại:

- `DEMO` / `CONTEST` → cho phép
- `REAL` → **BLOCK**, ngắt kết nối ngay, không đọc thêm bất kỳ dữ liệu nào
- `UNKNOWN` → từ chối (không suy đoán là DEMO)

Login luôn được mask (`*****4321`). Password không bao giờ rời khỏi `SecretStr`.

## Symbol discovery

Không hard-code symbol. `SymbolResolver` đọc danh sách từ terminal và map tên canonical (`EURUSD`) sang tên broker (`EURUSDm`, `EURUSDc`, `EURUSD.a`, `mEURUSD`).

Nếu nhiều symbol cùng khớp và không có match chính xác → `SYMBOL_MAPPING_AMBIGUOUS`, resolver **không tự chọn**.

Ba tên được giữ tách bạch: `name` (broker), `normalized` (đã bỏ ký tự phân cách), `canonical` (tên ALM dùng ở toàn bộ downstream).

## Terminal không sẵn sàng

Thiếu package hoặc terminal chưa chạy không làm sập hệ thống:

- `MT5_PACKAGE_NOT_INSTALLED`
- `MT5_TERMINAL_NOT_AVAILABLE`
- `MT5_NOT_CONNECTED`

API vẫn phục vụ bình thường và dashboard hiển thị `OFFLINE`.
