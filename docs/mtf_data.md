# Dữ liệu database đa khung thời gian

Market Regime Engine tải candle D1, H4, H1, M15, M5 và M1 đã đóng từ database. Candle native của provider được ưu tiên. Chuỗi suy ra có kiểm soát chỉ dùng khi timeframe native được yêu cầu không tồn tại.

Thẩm quyền khung lớn vẫn thuộc D1/H4/H1. M15/M5/M1 mô tả hướng khung thấp, setup và retracement; chúng không định nghĩa lại toàn thị trường thành bullish hoặc bearish.

Backtest dùng `BacktestDataLoader` với symbol, timeframe, start, end, source và `as_of`. Một hàng phải vừa có `is_closed=true`, vừa thỏa `timestamp + timeframe duration <= as_of`. Vì vậy candle T+1 tương lai và candle HTF chưa hoàn tất không thể đi vào snapshot tại T.

Chiều phụ thuộc vẫn là:

```text
DATA -> FEATURES -> MARKET REGIME -> STRATEGY -> RISK -> EXECUTION
```

Phase 2 chỉ triển khai DATA và ranh giới đọc an toàn. Nó không train machine-learning model hoặc gọi execution.
