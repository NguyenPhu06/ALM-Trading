# Indicator Engine

Indicator được tính độc lập cho từng timeframe trên tiền tố nhân quả gồm các candle đã đóng.

- RSI(14): trung bình số học của 14 mức tăng và giảm gần nhất, `100 - 100/(1 + average_gain/average_loss)`. Feature gồm threshold, phía so với midline, slope một bước, phục hồi khỏi oversold, phân kỳ close/RSI xác định và dấu hiệu kiệt sức khả dĩ.
- ATR(14): trung bình số học của 14 true range gần nhất, với `TR = max(high-low, |high-prev_close|, |low-prev_close|)`.
- ADX(14): directional movement dương/âm rolling chia cho tổng true range, sau đó lấy trung bình 14 giá trị DX gần nhất. Đầu ra gồm `+DI`, `-DI`, hướng, tăng/giảm và `NO_TREND`, `WEAK_TREND`, `MODERATE_TREND` hoặc `STRONG_TREND`.
- Volatility: ATR percentage, độ lệch chuẩn tổng thể của close return và percentile range mới nhất. Các dải percentile được ánh xạ thành biến động thấp, bình thường, cao hoặc cực đoan.

Thông số Ichimoku mặc định là Tenkan 9, Kijun 26, Senkou B 52 và displacement 26. Tenkan/Kijun cùng leading span vừa tính chỉ dùng dữ liệu hiện có. So sánh cloud tại candle hiện tại dùng span đã tính 26 bar trước; tọa độ plot dịch về tương lai không bao giờ được đọc như thông tin hiện tại. Chikou công bố giá close hiện đã biết cùng timestamp tính toán, không đọc close tương lai tại vị trí plot lùi về sau.
