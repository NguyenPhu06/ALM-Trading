# Bảo vệ chống look-ahead

Các phép tính Phase 1B được thiết kế theo nguyên tắc nhân quả.

## Quy tắc

1. Candle phải là bản ghi database có thứ tự và `is_closed=true`. Engine dừng tại candle mở đầu tiên ngay cả khi được gọi ngoài pipeline.
2. Ứng viên fractal không hiển thị cho đến khi toàn bộ bar phía phải theo cấu hình đã đóng. Production Phase 1B.1 yêu cầu hai right bar.
3. `event_timestamp` là thời điểm đầu tiên sự kiện có thể được biết.
4. `confirmation_timestamp` ghi thời điểm xác nhận swing/level khi áp dụng.
5. Mức ngày trước và session trước chỉ xuất hiện sau khi period tương ứng chuyển tiếp.
6. High/low của session hiện tại là trạng thái đang chạy, không phải cực trị cuối session trong tương lai.
7. MTF và snapshot lọc mọi sự kiện tại timestamp `as_of` rõ ràng.
8. Pipeline Phase 1B đọc `market_candles` theo thứ tự thời gian từ database; không tạo candle còn thiếu.
9. Tổng hợp M15→H1/H4/D1 chỉ phát bucket UTC hoàn chỉnh. `close_time` của HTF là thời điểm sớm nhất được phép sử dụng.
10. MTF alignment chọn sự kiện cuối cùng có cả event timestamp và confirmation timestamp nhỏ hơn hoặc bằng thời điểm đóng M15.

`test_swing_detection_requires_right_confirmation_bar` chứng minh ứng viên chưa khả dụng trước right bar. `test_future_extension_cannot_change_past_decisions` so sánh phép tính trên prefix với cùng prefix nằm trong chuỗi tương lai dài hơn. Các test snapshot và session độc lập xác nhận sự kiện cùng high/low về sau vẫn không nhìn thấy.

Backtest phải tính tăng dần hoặc truyền cutoff `as_of_index`/`as_of`. Dùng danh sách swing cuối cùng mà không tôn trọng confirmation timestamp của từng sự kiện sẽ vi phạm contract này.

Regression test snapshot so sánh snapshot tính từ một prefix candle với snapshot tại cùng timestamp sau khi thêm candle tương lai. Kết quả phải giống hệt nhau.
