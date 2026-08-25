# Liquidity Engine

Liquidity Engine Phase 1B suy ra các giả thuyết có thể kiểm toán từ candle đã lưu trong PostgreSQL/TimescaleDB. Thanh khoản không đồng nghĩa chắc chắn có lệnh tổ chức, và liquidity sweep không đảm bảo đảo chiều.

## Các mức

Engine phát sự kiện `LIQUIDITY_LEVEL` cho:

- swing high và swing low đã xác nhận;
- equal high và equal low theo tolerance;
- high và low của ngày trước, chỉ khả dụng tại candle quan sát đầu tiên của ngày UTC tiếp theo;
- high và low đang chạy của session hiện tại;
- high và low của session đã hoàn tất trước đó.

Session có thể cấu hình và được tính theo timezone IANA đã chọn, trong khi timestamp lưu trữ vẫn là UTC. Cửa sổ mặc định: Asia 00:00–09:00, London 07:00–16:00 và New York 13:00–22:00 UTC. Thời gian London/New York đồng thời được gắn `LONDON_NEW_YORK_OVERLAP`; `OVERLAP` vẫn là enum alias tương thích.

## Sweep

Bearish sweep yêu cầu một mức high đã biết từ trước, wick vượt lên trên, close quay xuống dưới mức đó và đạt rejection ratio tối thiểu có thể cấu hình. Bullish sweep áp dụng điều kiện ngược lại cho mức low đã biết. Metadata gồm level, penetration, rejection, rejection ratio, `close_back_inside`, thời điểm level được biết và tuổi theo số bar. Wick nằm xa một level đã biết không phải sweep.

## Độ mạnh

Điểm 0–100 mang tính xác định. Các thành phần có giới hạn gồm khoảng cách chuẩn hóa, số lần chạm, tuổi, trọng số timeframe, equal-level, swing strength và session relevance. Đây chỉ là feature engineering; không fit model và không tạo dữ liệu training AI tổng hợp.

Thuật ngữ SMC/ICT trong ALM đại diện cho giả thuyết thị trường có thể kiểm thử, không phải sự thật đã được chứng minh về hành vi market maker.
