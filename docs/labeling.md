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
