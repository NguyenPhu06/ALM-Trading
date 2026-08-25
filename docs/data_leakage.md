# Bảo vệ chống rò rỉ dữ liệu tương lai

Feature và label có ranh giới thông tin khác nhau.

- Feature tại T chỉ được dùng candle đã đóng có thời điểm đóng nhỏ hơn hoặc bằng T.
- Candle H1 mở lúc 10:00 chưa khả dụng cho M15 lúc 10:15, 10:30 hoặc 10:45; nó chỉ khả dụng từ 11:00.
- Swing đã xác nhận chỉ xuất hiện từ `confirmation_timestamp`.
- Resampling chỉ phát hành bucket UTC hoàn chỉnh và không tự lấp candle thiếu.
- Chỉ Label Engine chạy offline mới được truy cập candle tương lai.

Dataset Builder kiểm tra trạng thái của từng khung thời gian được chọn so với T. `tests/test_no_future_leakage.py` thay đổi một candle tương lai và chứng minh feature vector thô tại T không đổi. Test cũng chứng minh điều kiện thời gian đóng của HTF và xác nhận các trường future/MFE/MAE không đi vào feature.

Normalization là một ranh giới leakage khác. Standardizer chỉ fit mean và standard deviation trên phân vùng TRAIN theo thời gian. Cùng một scaler đã đóng băng được dùng để transform TRAIN, VALIDATION và TEST; thống kê validation/test không bao giờ được dùng để fit.

Dataset được chia theo thời gian và không shuffle. Dataset hash bao gồm feature, feature đã chuẩn hóa, label, phân vùng và schema hash để phát hiện thay đổi ngoài ý muốn.
