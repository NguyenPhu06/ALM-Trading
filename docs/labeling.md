# Gán nhãn Phase 4

`FEATURE != LABEL`.

Feature mô tả những gì có thể biết tại timestamp T. Label đo lường diễn biến từ T+1 trở đi và chỉ được tạo sau khi toàn bộ feature đã hoàn tất.

Với base candle M15, Label Engine tính return close-to-close sau 1, 3, 5 và 10 candle tương lai. MFE dùng high tương lai lớn nhất so với close tại T. MAE dùng low tương lai nhỏ nhất so với close tại T.

Ngưỡng phân loại được cấu hình tại `phase_4.classification_threshold`:

- return sau năm candle lớn hơn ngưỡng: `UP`;
- return nhỏ hơn âm của ngưỡng: `DOWN`;
- các trường hợp còn lại: `NEUTRAL`.

Outcome threshold được cấu hình độc lập. Kết quả long và short là `FAVORABLE`, `ADVERSE`, `MIXED` hoặc `NEUTRAL`, tùy việc excursion thuận lợi/bất lợi có vượt ngưỡng hay không. Giữ `MIXED` vì candle OHLC không thể chứng minh biên intrabar nào xảy ra trước.

Các target này dành cho supervised learning và nghiên cứu strategy. Chúng không phải signal, tuyên bố lợi nhuận hay quyền thực thi lệnh.

## Phase 13 — gán nhãn forward-only, có tính chi phí

`ai/dataset/labels.py` (`LABEL_VERSION = "labels_v1"`) gán nhãn cho observation thật thay vì candle lịch sử, nên quy tắc quan trọng nhất là **thời gian**.

`LabelingEngine` từ chối gán nhãn khi:

- `now < entry_time + horizon` — horizon chưa trôi qua, tương lai chưa tồn tại;
- cửa sổ dữ liệu không chạm tới deadline — không đủ dữ liệu để kết luận.

Lý do từ chối là enum `LabelRefusal`, được đếm trong `DatasetAudit`. Từ chối là hành vi đúng; không có nhánh nào ngoại suy hay điền tạm.

Horizon (`HORIZONS`) trải từ 5 phút tới 24 giờ, cấu hình ở `phase_13.horizons`.

Nhãn có tính **chi phí giao dịch** (`TradingCosts`: spread, commission, swap ước tính). Một chuyển động nhỏ hơn chi phí không phải cơ hội, nên nó là `NEUTRAL` chứ không phải `UP` hay `DOWN`. Việc này ép model học các cơ hội thực sự trả tiền được, không phải nhiễu.

`ForwardLabel` ghi kèm horizon, label version và timestamp gán nhãn để có thể truy vết.

Xem thêm: [dataset_pipeline.md](dataset_pipeline.md), [lookahead_protection.md](lookahead_protection.md).
