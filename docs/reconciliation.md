# Reconciliation

Sau khi gửi lệnh, hệ thống so khớp ba nguồn: **request** đã gửi, **result** MT5 trả về, và **position** thực tế trên terminal.

## Kiểm tra

| Mục | Sai lệch |
| --- | --- |
| ticket | `MISSING_BROKER_TICKET` |
| volume | `VOLUME_MISMATCH` |
| price | `PRICE_DEVIATION`, `MISSING_FILL_PRICE` |
| position | `POSITION_MISSING`, `POSITION_VOLUME_MISMATCH`, `POSITION_TICKET_MISMATCH` |
| PnL | `PNL_UNAVAILABLE` |
| SL | `SL_NOT_SET`, `SL_MISMATCH` |
| TP | `TP_NOT_SET`, `TP_MISMATCH` |

## Trạng thái

- `MATCHED` — mọi kiểm tra pass
- `MISMATCHED` — có sai lệch
- `POSITION_MISSING` — lệnh khớp nhưng không tìm thấy position
- `NOT_APPLICABLE` — lệnh bị chặn/từ chối nên không có gì để so

## Chỉ báo cáo, không sửa

Reconciliation **không bao giờ** gửi lệnh chỉnh sửa. Sai lệch được ghi vào `reconciliation_records`, ghi audit stage `RECONCILIATION`, và phát alert `RECONCILIATION_FAILED`. Việc xử lý thuộc về người vận hành.

Test `test_reconciliation_reports_but_never_repairs` khẳng định không có lệnh thứ hai nào được gửi.

## Ngưỡng

`config/settings.yaml` → `phase_11.reconciliation`: `volume_tolerance` (0.0001), `price_tolerance` (0.0010).
