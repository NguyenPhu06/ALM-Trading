# Market Intelligence Engine

Phase 3 chuyển candle chuẩn hóa đã đóng thành trạng thái có thể giải thích. Hệ thống dừng ở market intelligence và không bao giờ phát hoặc thực thi chỉ thị `BUY`, `SELL`, DCA hay broker.

Với mỗi khung D1, H4, H1, M30, M15, M5 và M1, `MarketIntelligenceEngine` tính OHLCV, internal/swing structure, liquidity, premium/discount, feature SMC/price action, indicator, volatility và thống kê session nhân quả. Ưu tiên candle database native từ provider. Hàng mẫu `local_csv` chỉ dùng cho test và bị loại mặc định. Resampler có kiểm soát của Phase 2 chỉ dùng khi thiếu timeframe native; M30 có thể được tạo từ hai candle M15 hoàn chỉnh.

Tại `as_of = T`, candle chỉ được đưa vào khi `is_closed = true` và `candle open timestamp + timeframe duration <= T`. Mỗi detector nhận đúng prefix đó. Vì vậy, thêm candle sau T không thể thay đổi RSI, ADX, ATR, Ichimoku, BOS, CHoCH, FVG, order block, sweep, bias, confluence hay feature vector tại T.

`MarketStateSnapshot` chứa timestamp tính toán, symbol, bảy trạng thái timeframe độc lập, bias phân cấp, lý do/xung đột confluence, lý do `NO_TRADE` và feature vector có version. `signal` luôn là `null`.

MTF regime xác định giữ `higher_timeframe_bias` (D1/H4/H1) tách khỏi `lower_timeframe_state` (M30/M15/M5). Đầu ra là `ALIGNED`, `COUNTER_TREND`, `MIXED` hoặc `INSUFFICIENT`, kèm confidence dựa trên độ phủ timeframe bắt buộc, mức đồng thuận HTF và alignment. Regime từng timeframe là bullish, bearish, ranging, transitional, conflicting hoặc unknown.

Có thể lưu snapshot bằng:

```text
python -m scripts.calculate_market_intelligence --symbol EURUSD --as-of 2026-08-24T09:00:00Z
```

Đây là feature engineering trạng thái thị trường có tính xác định, không phải dự đoán hay xác suất giao dịch đã được kiểm chứng.
