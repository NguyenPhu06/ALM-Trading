# Market regime đa khung thời gian

Lớp regime không coi M15 là xu hướng chính. Vai trò được cố định: D1 là macro regime, H4 là xu hướng cấu trúc chính, H1 xác nhận hướng giao dịch, M15 là ngữ cảnh liquidity/setup, M5 tinh chỉnh điểm vào và M1 là thời điểm execution tùy chọn. Dữ liệu M5/M1 thiếu được thể hiện rõ và không bao giờ được tạo bằng cách chia nhỏ timeframe lớn.

## Ma trận cấu trúc

Mỗi timeframe được xử lý độc lập qua candle đã đóng, swing confirmation có độ trễ, structure và liquidity. Xu hướng có hướng yêu cầu chuỗi cấu trúc:

- HH + HL + bullish BOS → bullish;
- LH + LL + bearish BOS → bearish;
- bằng chứng thiếu hoặc xung đột → neutral/transitional.

Một candle, indicator, wick hoặc CHoCH M15 đơn lẻ không thể xác định regime. Xu hướng trải từ `STRONGLY_BEARISH` đến `STRONGLY_BULLISH` và có structural strength đã chuẩn hóa.

## Tách HTF và LTF

`HTF_BIAS` chỉ dùng D1/H4/H1. `LTF_DIRECTION` dùng M15/M5/M1. Điểm cấu trúc có cấu hình mặc định D1 40%, H4 30%, H1 20% và M15 10%, nên nhiễu khung thấp không thể chi phối điểm. Hướng LTF đối lập được gắn là retracement hoặc bằng chứng reversal, không bao giờ là `BUY`/`SELL`.

Reversal confidence chỉ tăng qua chuỗi nhân quả: liquidity sweep đã biết, LTF CHoCH, xác nhận cấu trúc M15, xác nhận H1 rồi xác nhận H4. Riêng M15 vẫn có confidence thấp.

## Indicator và đầu vào tổ chức

RSI, ADX, ATR và Ichimoku được tính độc lập theo candle đã đóng của từng timeframe. Chúng cung cấp metadata xác nhận/xung đột và không bao giờ viết lại xu hướng cấu trúc. Thiếu lịch sử được thể hiện rõ.

Đầu vào tổ chức là tùy chọn và có timestamp. ALM có thể dùng thành phần institutional-pressure đã lưu hoặc dữ liệu CFTC COT đã ánh xạ. Các trường bank participation và CME vẫn không khả dụng nếu chưa có nguồn thật. Giá trị thiếu không được tổng hợp giả.

## Ranh giới strategy

Strategy nhận `MarketRegimeSnapshot`, không nhận raw candle, để quyết định regime. Snapshot chứa hướng HTF/LTF, trạng thái thị trường, reversal confidence, điểm có trọng số, liquidity map, indicator độc lập, alignment timeframe và xung đột. `signal` luôn là `null` trong phase này; Regime Engine không đặt hoặc khuyến nghị giao dịch.
