# MT5 trên Windows, API trong Docker

## Ràng buộc

Package `MetaTrader5` chỉ điều khiển được terminal **trên cùng máy Windows**. Nó giao tiếp với terminal qua IPC nội bộ, không phải qua mạng.

Vì vậy: **container Linux không thể trực tiếp điều khiển MT5 terminal chạy trên Windows host.** Không có workaround an toàn cho việc này. Wine, mount socket hay chia sẻ file terminal đều không được dùng.

## Hai kiến trúc được hỗ trợ

### A. API chạy trực tiếp trên Windows (khuyến nghị cho Phase 10)

```
Windows host
├── MetaTrader 5 terminal (Exness, DEMO)
└── ALM API (uvicorn, native Windows)
        └── MT5ReadOnlyClient  →  MetaTrader5 IPC
```

Cài thêm: `pip install MetaTrader5` (chỉ có wheel cho Windows).

Database vẫn có thể chạy trong Docker; chỉ API cần chạy native.

### B. Windows Read-Only Bridge (khi API phải ở trong Docker)

```
Windows host                          Docker
├── MetaTrader 5 terminal
└── ALM MT5 Bridge (native)  ──HTTP──►  ALM API
        MT5ReadOnlyClient                 MT5BridgeClient
```

Bridge là một tiến trình nhỏ chạy trên Windows, expose đúng các read endpoint (`/account`, `/tick`, `/rates`, `/positions`, `/orders`, `/health`) và **không có endpoint ghi nào**.

Cấu hình phía API:

```
MT5_BRIDGE_URL=http://host.docker.internal:8100
MT5_BRIDGE_TOKEN=<shared secret>
```

Yêu cầu bắt buộc với bridge:

- chỉ bind `127.0.0.1` hoặc mạng nội bộ, không expose ra Internet
- xác thực bằng token, token nằm trong `.env`, không hard-code
- không có route nào nhận order/close/modify
- áp dụng cùng `MT5SafetyLock` và cùng ràng buộc DEMO-only

**Trạng thái:** kiến trúc bridge đã được thiết kế và cấu hình đã có chỗ (`mt5_bridge_url`, `mt5_bridge_token`), nhưng tiến trình bridge **chưa được implement** trong Phase 10. Hiện tại dùng kiến trúc A.

## Phát hiện môi trường

`load_mt5_module()` trả `None` khi không import được, và hệ thống báo:

- `MT5_PACKAGE_NOT_INSTALLED` — chạy trên Linux/Docker hoặc chưa cài package
- `MT5_TERMINAL_NOT_AVAILABLE` — có package nhưng terminal chưa chạy / initialize thất bại

Cả hai đều **không làm sập** API. Dashboard hiển thị `OFFLINE` và mọi endpoint khác vẫn hoạt động.

## docker-compose

Service `api` trong compose vẫn là Linux và **không** kỳ vọng có MT5. Biến MT5 được truyền vào để cấu hình bridge về sau; khi không có bridge, MT5 đơn giản báo `OFFLINE`.
