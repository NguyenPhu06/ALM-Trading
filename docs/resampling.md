# Resampling có kiểm soát

Ưu tiên timeframe native của provider. Resampling chỉ là phương án dự phòng khi thiếu timeframe native và được giới hạn ở:

- M1 sang M5;
- M5 sang M15;
- M15 sang M30;
- M15 sang H1;
- H1 sang H4;
- H4 sang D1.

Bucket được căn theo UTC và yêu cầu đủ mọi source candle đã đóng theo kỳ vọng. Open, high, low, close và volume lần lượt dùng giá đầu, cực đại, cực tiểu, giá cuối và tổng. Bucket thiếu hoặc có gap bị bỏ, không được lấp. Bản ghi suy ra giữ `source_timeframe`, `target_timeframe` và `UTC_COMPLETE_BUCKET_OHLCV_V1`.

Bucket H1 bắt đầu lúc 10:00 chỉ quan sát được từ 11:00. Tại 10:15 nó bị loại dù một số thành phần M15 đã tồn tại. Không candle về sau nào được dùng để tạo hoặc công bố quyết định sớm hơn.
