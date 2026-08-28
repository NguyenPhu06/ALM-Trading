# MT5 DEMO Validation

## DemoAccountValidator

Bốn kết quả tường minh, chỉ một cho phép đi tiếp:

| Kết quả | Nghĩa |
| --- | --- |
| `VALID_DEMO` | account DEMO/CONTEST đã xác minh, server khớp mẫu DEMO |
| `INVALID_ACCOUNT` | account REAL, server không phải DEMO, hoặc terminal API bị chặn |
| `UNKNOWN_ACCOUNT` | không xác minh được trade mode hoặc broker/server |
| `CONNECTION_ERROR` | không có terminal, chưa kết nối, không đọc được account |

**UNKNOWN không bao giờ được coi là an toàn.** Bất kỳ kết quả nào khác `VALID_DEMO` đều chặn.

Account `REAL` có ưu tiên cao nhất: nó được báo `ACCOUNT_IS_REAL` ngay cả khi terminal đã ngắt kết nối, vì client read-only tự ngắt khi gặp REAL — nếu kiểm tra kết nối trước, lý do sẽ bị làm mờ thành `CONNECTION_ERROR`.

## Kiểm tra terminal

- terminal available / initialized / connected
- account login (đã mask), server, broker, account type
- terminal build
- terminal permissions: `trade_allowed`, `tradeapi_disabled`
- symbol availability, market availability

Không log password, secret, token hay credential. Payload công khai chỉ chứa login đã mask.

## Khi terminal không có

`MT5_PACKAGE_NOT_INSTALLED` hoặc `MT5_TERMINAL_NOT_AVAILABLE`. Hệ thống **không sập**; observation cycle dừng ở stage `ACCOUNT` và ghi lý do.

Trên máy không có MetaTrader5, integration test được **skip** với lý do rõ ràng, không biến thành failure.
