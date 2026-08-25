# Schema feature có version

Mỗi feature Phase 3 gồm thời điểm tính toán hoặc `as_of`, symbol, timeframe và `calculation_version = phase3.v1`. Nhờ vậy, định nghĩa có thể thay đổi dưới version mới mà không trộn âm thầm các training dataset.

Numeric vector ổn định chứa theo thứ tự:

1. mã hóa xu hướng D1, H4, H1, M30, M15, M5, M1 (`-1` giảm, `0` chưa rõ/đi ngang, `1` tăng);
2. RSI cho D1, H4, H1, M30, M15, M5;
3. ADX cho D1, H4, H1, M30, M15, M5;
4. ATR cho H1, M15, M5;
5. khoảng cách/loại thanh khoản gần nhất M15, hướng sweep, khoảng cách FVG, khoảng cách order block, premium/discount, Ichimoku, structure, BOS, CHoCH, spread và placeholder news-risk;
6. mã hóa phân loại session và volatility state của M15.

Feature số bị thiếu được mã hóa thành 0 và vẫn phân biệt được thông qua trường `available` của timeframe và `missing_reason` của indicator trong structured snapshot. Cả `names` và `values` có thứ tự đều được lưu để consumer có thể từ chối schema không tương thích.

`market_intelligence_snapshots` lưu trạng thái JSON và feature vector có version, khóa theo symbol, timeframe, event timestamp và calculation version. Candle thô không bị sao chép.
