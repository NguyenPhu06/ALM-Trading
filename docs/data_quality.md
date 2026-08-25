# Chất lượng dữ liệu thị trường

Mọi batch đầu vào được chuẩn hóa và kiểm tra trước khi ghi database. Kiểm tra bao gồm nhận biết UTC, cú pháp symbol/timeframe, timestamp tăng dần, duplicate theo source, giá OHLC hữu hạn và dương, quan hệ OHLC, cùng volume, tick volume và spread không âm.

Batch sai bị từ chối toàn bộ. Không sử dụng giá trị ngẫu nhiên, forward-fill, giá tổng hợp hoặc sửa dữ liệu im lặng.

`MarketDataGap` mô tả symbol, timeframe, khoảng thiếu, số lượng kỳ vọng/thực tế, mức nghiêm trọng và lý do. Detector dùng interval của candle và thời gian đóng cửa FX tiêu chuẩn theo UTC: từ thứ Sáu sau 22:00 đến Chủ Nhật trước 22:00 là thời gian thị trường đóng mang tính thông tin, không phải lỗi thiếu dữ liệu thông thường. Lịch nghỉ lễ và bảo trì riêng của provider chưa được mô hình hóa.

`DataFreshness` trả về `FRESH`, `STALE`, `MISSING` hoặc `ERROR` theo ngưỡng từng timeframe trong `config/settings.yaml`. Readiness kết hợp số lượng, độ mới, gap gần đây có ý nghĩa, số duplicate và số candle sai. Tính duy nhất theo source ngăn duplicate cùng nguồn trong database; validation ngăn candle sai được import.
