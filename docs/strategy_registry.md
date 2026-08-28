# Strategy Registry — Phase 15

Một chiến lược trong registry là một **bản khai báo**: nó đọc feature nào, nhìn timeframe nào, và luật entry / exit / DCA / risk là gì. Registry lưu bản khai báo đó cùng trạng thái mà nó đã *giành được*. Nó không chạy luật nào — `as_dict()` ghi rõ `"executes": false`.

## Trường bắt buộc

`strategy_id`, `strategy_version`, `description`, `features`, `timeframes`, `entry_rules`, `exit_rules`, `dca_rules`, `risk_rules`, `status`.

## Sáu trạng thái

```
EXPERIMENTAL -> TESTING -> VALIDATED -> CHAMPION -> RETIRED
             \-> REJECTED   \-> REJECTED   \-> REJECTED
```

`ALLOWED_TRANSITIONS` là bảng duy nhất. Nhảy cóc, lùi lại hay lặp một bước đều raise `TransitionRefused`. `REJECTED` và `RETIRED` là terminal — không có đường quay lại.

## CHAMPION không đến bằng transition

`transition(key, CHAMPION)` **raise** `PromotionRefused`. Cách duy nhất là `promote(key, ApprovalToken(...))`, và:

- `ApprovalToken` bắt buộc có tên người duyệt và lý do — chuỗi rỗng bị từ chối lúc khởi tạo;
- chỉ chiến lược ở `VALIDATED` mới được thăng hạng;
- truyền bất cứ thứ gì không phải `ApprovalToken` đều bị từ chối;
- champion cũ tự động chuyển `RETIRED` với ghi chú `SUPERSEDED_BY:<key>` — mỗi `strategy_id` chỉ có một champion.

## Fingerprint

`fingerprint` là hash nội dung của bản khai báo luật. Hai chiến lược giống hệt nhau nhưng khác tên sẽ trùng fingerprint, và `duplicates()` liệt kê chúng. Điều này quan trọng cho [multiple_testing.md](multiple_testing.md): đổi tên một chiến lược rồi thử lại không phải là một giả thuyết mới.

## Loại bỏ

`reject(key, reason)` bắt buộc có lý do và ghi nó vào `notes` dưới dạng `REJECTED:<lý do>`. Tiêu chí loại bỏ nằm ở `rejection_criteria()`:

- expectancy âm trên forward observation với mẫu đủ lớn;
- kém champion rõ rệt trên cơ sở risk-adjusted;
- chỉ có lãi ở một regime hoặc một session (không ổn định);
- confidence cao hơn accuracy một cách hệ thống (tự tin sai);
- kết quả không sống sót qua hiệu chỉnh multiple testing;
- kết quả chỉ tái lập được bằng cách đọc lại holdout.

## Lưu trữ

Bảng `research_strategies`, upsert theo `key`. Không cột nào chứa binary hay credential.

Xem thêm: [ai_research_lab.md](ai_research_lab.md), [champion_challenger.md](champion_challenger.md).
