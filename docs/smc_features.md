# Feature SMC và price action

Các định nghĩa này là giả thuyết xác định. Chúng không tuyên bố biết ý định market maker hay dòng lệnh thực của tổ chức.

## Fair value gap và imbalance

Với ba candle đã đóng liên tiếp `(i-2, i-1, i)`, bullish FVG tồn tại khi `low[i] > high[i-2]`; vùng là `[high[i-2], low[i]]`. Bearish FVG tồn tại khi `high[i] < low[i-2]`; vùng là `[high[i], low[i-2]]`. Kích thước phải đạt mức tối thiểu đã cấu hình. Candle về sau cập nhật tỷ lệ fill từ 0 đến 100 và trạng thái `OPEN`, `PARTIALLY_FILLED` hoặc `FILLED`. Snapshot trước candle fill vẫn không đổi.

## Displacement và rejection

True range được so sánh với rolling ATR. Candle được coi là displacement khi `range / ATR` vượt tỷ lệ cấu hình và `abs(close-open) / range` vượt body threshold. Hướng là hướng thân candle; volume ratio chỉ được đưa vào khi có volume thật.

Rejection là wick lớn hơn chia cho tổng range. Chỉ gắn cờ khi vượt wick threshold đã cấu hình.

## Order block và breaker block

Quy tắc order block ban đầu chọn candle ngược hướng gần nhất trong lookback đã cấu hình, đứng trước một displacement candle đủ điều kiện đóng vượt rolling high hoặc low. Toàn bộ range high-low của candle là zone. Việc overlap về sau đánh dấu mitigation. Nếu giá sau đó đóng hoàn toàn xuyên qua biên zone đối diện, nó được gắn `BREAKER_BLOCK`.

Các zone này không bao giờ tự động tạo lệnh.
