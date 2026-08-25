# Kiến trúc dữ liệu thị trường Phase 7

Luồng chuẩn là provider hợp pháp → normalizer UTC → kiểm tra chất lượng → PostgreSQL → feature/intelligence → strategy risk gate. Strategy không biết và không gọi trực tiếp provider.

Gateway hỗ trợ D1, H4, H1, M30, M15 và M5. Nếu nguồn chỉ có M1/M5, resampler chỉ tạo bucket lớn hơn khi đủ toàn bộ candle nguồn đã đóng. `OPEN_CANDLE` không được dùng cho indicator, snapshot lịch sử hoặc backtest.

Quality report gồm completeness, freshness, timestamp/OHLC integrity, duplicate rate và gap rate. Trạng thái `INVALID` chặn setup mô phỏng.

