# Market Structure Engine

Phase 1B xem market structure là feature engineering xác định, không phải dự đoán hay tuyên bố chắc chắn.

## Xác nhận swing nhân quả

`SwingDetector` dùng số fractal bar trái/phải, khoảng cách bar tối thiểu và mức dịch chuyển giá tối thiểu có thể cấu hình. Pipeline Phase 1B giữ cố định hai right bar; Phase 3 đọc cấu hình riêng. Ứng viên tại candle `i` chỉ được xác nhận sau khi candle `i + right_bars` đóng. Ứng viên chưa xác nhận được đánh dấu rõ và không đi vào phép tính structure. `confirmation_timestamp` là thời điểm đóng của candle xác nhận.

High đã xác nhận được phân loại so với high xác nhận trước là `HH` hoặc `LH`. Low đã xác nhận được phân loại là `HL` hoặc `LL`. Equal level dùng `equal_level_tolerance_points * point_size`; không yêu cầu số thực bằng nhau tuyệt đối.

## BOS và CHoCH

Chế độ mặc định `CLOSE_BREAK` yêu cầu close vượt level đã xác nhận. `WICK_BREAK` có thể bật qua cấu hình. Mỗi level chỉ bị phá một lần:

- phá theo hướng cấu trúc đang hoạt động là BOS;
- phá ngược cấu trúc bearish là bullish CHoCH;
- phá ngược cấu trúc bullish là bearish CHoCH.

Metadata CHoCH lưu `previous_structure`, `broken_level`, `new_direction`, break mode, thời điểm xác nhận level và displacement xác định. Candle chưa đóng và swing chưa xác nhận bị loại.

## Khung thời gian lớn

Resampler nhân quả tạo H1, H4 và D1 từ bucket M15 UTC đã đóng hoàn chỉnh. Open lấy giá đầu, high/low lấy cực trị, close lấy giá cuối và volume khả dụng được cộng lại. Bucket thiếu không bao giờ được truyền vào HTF Structure Engine.

## Bias và sử dụng đa khung

`StructureBias` trải từ `STRONG_BEARISH` đến `STRONG_BULLISH`. Điểm chỉ dùng BOS, CHoCH, HH/HL, LH/LL, displacement và trọng số timeframe. Không dùng RSI, ADX, Ichimoku hay machine learning.

MTF Analyzer giữ HTF bias tách biệt LTF structure. Ví dụ, hoạt động bullish M15 có thể chỉ là retracement trong bối cảnh D1/H4/H1 bearish; nó không gắn lại toàn thị trường thành bullish.

Market structure là một giả thuyết thị trường và không mang lại độ chắc chắn dự báo.

Phase 3 cũng công bố `BULLISH` cho chuỗi HH+HL gần đây, `BEARISH` cho LH+LL, `RANGING` khi các phân loại xác nhận bị trộn và `UNKNOWN` khi chuỗi cấu trúc chưa đủ. Mọi timeframe được hỗ trợ chạy cùng thuật toán cấu hình một cách độc lập.
