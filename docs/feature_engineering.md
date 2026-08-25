# Kỹ thuật xây dựng feature

Mỗi base candle đã đóng có thể tạo một `CandleFeatureRecord`. Tại thời điểm đóng T, `FeatureStore` yêu cầu Intelligence Engine tạo snapshot với `as_of=T`, vì vậy candle về sau không thể thay đổi bản ghi đó.

Vector gồm mã hóa xu hướng D1/H4/H1/M30/M15/M5/M1; RSI, ADX và ATR đa khung; trạng thái Ichimoku M15; mã hóa structure/BOS/CHoCH; premium/discount; khoảng cách và phía thanh khoản; khoảng cách sweep, FVG và order block; session; volatility; spread nếu có; cùng placeholder news-risk bằng 0 khi chưa có provider. Trạng thái thiếu dữ liệu được thể hiện rõ trong `data_quality`, không bị nhầm với giá trị 0 quan sát được.

Premium/discount dùng trung điểm của swing high và swing low đã xác nhận gần nhất. Giá trên trung điểm là premium, dưới là discount, bằng nhau là equilibrium. Internal structure dùng cửa sổ swing nhân quả 1-left/1-right; swing structure dùng số bar xác nhận rộng hơn theo cấu hình. Cả hai chỉ ghi sự kiện đã xác nhận.

`phase3.v1` đi kèm các trường snapshot và vector. Khi thay đổi định nghĩa phải dùng version mới, không được âm thầm viết lại input training lịch sử.
