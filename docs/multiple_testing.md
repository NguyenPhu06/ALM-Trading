# Multiple Testing & Holdout — Phase 15

## Vấn đề

Thử hai mươi chiến lược ở mức 5% thì **một cái sẽ trông có lãi do ngẫu nhiên**. Đó không phải một phát hiện; đó là số học.

`ExperimentLedger` tồn tại để sự thật đó luôn nhìn thấy được, chứ không bị quên đi giữa các lần chạy.

## Sổ ghi

Ledger đếm:

- `experiment_count` — số **cấu hình khác nhau** đã thử;
- `hypotheses_tested` — **mọi** lần kiểm định, kể cả lặp lại cùng một cấu hình;
- `selection_method` — `PRE_REGISTERED`, `BEST_OF_N`, `SEQUENTIAL`, `EXPLORATORY`;
- `holdout_usage` — số lần holdout bị đọc.

Chạy lại cùng một `experiment_id` đếm **một** thí nghiệm nhưng **hai** giả thuyết — và phát cảnh báo `REPEATED_TESTS_ON_SAME_CONFIGURATION`.

## Hiệu chỉnh

`adjusted_alpha = alpha / hypotheses_tested` (Bonferroni). Hai mươi lần thử ở alpha 0.05 nâng hàng rào lên 0.0025 — một p-value 0.04 "may mắn" **không sống sót**, và ledger phát `NO_RESULT_SURVIVES_MULTIPLE_TESTING_CORRECTION`.

`benjamini_hochberg()` cũng được báo cáo (kiểm soát FDR, ít bảo thủ hơn Bonferroni) để quyết định không bị kẹt vào một hiệu chỉnh duy nhất.

`BEST_OF_N` luôn kèm cảnh báo `BEST_OF_N_SELECTION_INFLATES_APPARENT_EDGE`: chọn cái tốt nhất trong N là chính xác cái làm phồng lợi thế biểu kiến.

## Holdout (section 17)

`HoldoutGuard` tách **theo thời gian**: holdout luôn là phần đuôi *gần nhất*, mặc định 20%. Một holdout ngẫu nhiên sẽ rò rỉ tương lai.

Chế độ hỏng mà nó canh không phải sự gian dối — mà là người nghiên cứu xem holdout, chỉnh một tham số, rồi xem lại. Sau ba vòng như thế, holdout đã là dữ liệu huấn luyện mang tên khác.

Guard **không thể** ngăn cái nhìn thứ hai về mặt vật lý. Nó làm ba việc:

- `peek()` bắt buộc có lý do, và **từ chối** khi budget (mặc định 1) đã dùng hết — lỗi nêu tên các lần đọc trước;
- mọi lần đọc được ghi lại kèm lý do và thời điểm, và báo lên ledger;
- `final_result_valid` chuyển `False` ngay khi holdout bị đọc quá một lần, kèm cảnh báo `HOLDOUT_READ_MORE_THAN_ONCE`.

`assert_untouched()` bảo vệ những gì phải chạy trước khi holdout mở. `contains_holdout()` phát hiện một tập "chỉ research" thò vào cửa sổ holdout.

Xem thêm: [statistical_significance.md](statistical_significance.md), [ai_research_lab.md](ai_research_lab.md).
