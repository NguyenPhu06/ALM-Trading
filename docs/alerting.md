# Alert Engine

Alert types gồm liquidity sweep, BOS, CHoCH, MTF conflict, strategy ready/invalidated, paper entry, DCA trigger/block, exit, risk warning/block, model/data/provider errors. Severity gồm LOW, MEDIUM, HIGH, CRITICAL.

## Một nguồn lưu trữ duy nhất

Alert được ghi và đọc trên cùng bảng `dashboard_alerts`. `AlertRepositoryNotificationProvider` đẩy mọi alert phát ra xuống database, và `AlertEngine.list()` đọc lại qua chính provider đó, nên `/dashboard/alerts` luôn thấy đúng những gì đã phát. Không còn hai kho riêng biệt.

`DashboardNotificationProvider` in-memory chỉ còn dùng cho test. Webhook/email/Telegram vẫn là interface unavailable; không hard-code credential.

## Sự kiện được nối

`AlertRouter` dịch kết quả domain thành alert, nên strategy/risk/paper không cần biết gì về alerting:

| Sự kiện | Alert type | Severity |
| --- | --- | --- |
| Strategy INVALIDATE | `STRATEGY_INVALIDATED` | HIGH |
| Strategy SIMULATE | `STRATEGY_READY` | MEDIUM |
| Xung đột khung thời gian | `MTF_CONFLICT` | MEDIUM |
| Paper entry thành công | `PAPER_ENTRY` | MEDIUM |
| Paper entry bị từ chối | `RISK_BLOCK` | HIGH |
| DCA thành công | `DCA_TRIGGER` | MEDIUM |
| DCA bị chặn bởi risk | `DCA_BLOCKED` | MEDIUM |
| Paper exit | `EXIT_TRIGGER` | MEDIUM |
| Data quality failure | `DATA_ERROR` | CRITICAL |
| Provider unavailable | `PROVIDER_ERROR` | HIGH |
| Model failure | `MODEL_ERROR` | HIGH |
| Kill switch bật/tắt | `RISK_BLOCK` | CRITICAL / MEDIUM |

Rejection do data, provider hoặc model giữ nguyên type gốc kể cả trong ngữ cảnh DCA: một DCA bị chặn vì dữ liệu hỏng là `DATA_ERROR`, không phải chỉ là `DCA_BLOCKED`. Kill switch chỉ phát alert khi trạng thái đổi, không phát lại mỗi tick.

API hỗ trợ lọc symbol, type, severity và unread.
