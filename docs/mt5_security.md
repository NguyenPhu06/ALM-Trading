# MT5 Security

## Credentials

`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER` chỉ tồn tại trong `.env`. `.env` nằm trong `.gitignore` và không được track.

- Password là `pydantic.SecretStr` — `repr()`/`str()` của Settings không bao giờ chứa giá trị thật.
- Password chỉ được lấy ra đúng một lần, ngay tại `MetaTrader5.initialize(...)`.
- Không có credential nào trong source code, log, database hay API response.

## Logging

`MT5Connection.connect()` truyền password vào `kwargs` của terminal nhưng **không bao giờ log `kwargs`**. Khi initialize raise, chỉ tên kiểu exception được log:

```python
logger.exception("MT5 initialize raised %s", type(error).__name__)
```

Test `test_connecting_never_writes_the_password_to_the_log` và `test_a_terminal_failure_does_not_leak_the_password` kiểm tra cả đường thành công lẫn đường lỗi.

## Database

Không bảng `mt5_*` nào có cột password/secret/token. Bảng account chỉ lưu `login_masked`.

`scrub()` loại đệ quy mọi key chứa `password`, `secret`, `token`, `credential`, `api_key` trước khi ghi bất kỳ JSON payload nào — kể cả khi caller vô tình truyền vào.

## API

Không endpoint nào trả credential. `test_no_mt5_endpoint_returns_a_credential` duyệt JSON của cả 11 endpoint, kiểm tra theo **key** chứ không theo substring, và khẳng định giá trị bí mật cùng login thật không xuất hiện.

Login luôn hiển thị dạng mask: `987654321` → `*****4321`.

## Read-only

- Không có `POST /mt5/order`, `/mt5/close`, `/mt5/modify`.
- Chỉ có `POST /mt5/connect` và `POST /mt5/disconnect`, cả hai chỉ mở/đóng phiên đọc.
- `MT5ReadOnlyClient` không có method thực thi nào.

## Account

Tài khoản `REAL` bị chặn và ngắt kết nối ngay lập tức; không đọc dữ liệu, không thao tác gì. Chỉ `DEMO`/`CONTEST` được chấp nhận, `UNKNOWN` bị từ chối.

## Security scan checklist

| Kiểm tra | Test |
| --- | --- |
| `.env` không tracked | `test_env_is_not_tracked_by_git` |
| Không credential literal trong source | `test_no_credential_literal_is_committed_in_source` |
| Không credential trong log | `test_connecting_never_writes_the_password_to_the_log` |
| Không credential trong database | `test_no_mt5_table_has_a_credential_column`, `test_persisted_rows_contain_no_credential_and_only_a_masked_login` |
| Không credential trong API | `test_no_mt5_endpoint_returns_a_credential` |
| Không live execution code | `test_mt5_cannot_execute_trade`, `test_no_module_in_the_mt5_package_calls_an_execution_function` |
| Không order API | `test_no_api_route_can_submit_an_mt5_order`, `test_mt5_routes_are_read_only` |
