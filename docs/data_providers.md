# Nhà cung cấp dữ liệu

`BaseMarketDataProvider` cô lập các thao tác connect, disconnect, historical, latest, incremental và health. Định dạng phản hồi riêng của provider không đi vào feature, backtest, strategy hay repository.

Adapter ban đầu dùng REST API được cấp quyền của Twelve Data. API time-series được tài liệu hóa hỗ trợ FX, các interval native cần thiết, đầu ra UTC, khoảng ngày giới hạn và tối đa 5.000 điểm mỗi request. Adapter chia nhỏ request lớn, giới hạn tần suất, retry hữu hạn với exponential backoff, đặt timeout và không bao giờ ghi API key vào log. Xem [tài liệu API](https://twelvedata.com/docs), [hướng dẫn dữ liệu lịch sử](https://support.twelvedata.com/en/articles/5656039-how-to-get-historical-prices) và [mô hình credit](https://support.twelvedata.com/en/articles/5615854-credits).

Cấu hình chỉ qua biến môi trường:

```text
MARKET_DATA_PROVIDER=historical
MARKET_DATA_API_KEY=
MARKET_DATA_BASE_URL=https://api.twelvedata.com
MARKET_DATA_TIMEOUT=30
MARKET_DATA_RATE_LIMIT=8
MARKET_DATA_MAX_RETRIES=3
MARKET_DATA_BACKOFF_SECONDS=1
```

Thiếu API key tạo trạng thái `UNCONFIGURED`; hệ thống không tự chuyển sang dữ liệu mẫu hoặc TradingView. TradingView vẫn là đầu vào webhook/visualization độc lập, không phải price feed máy đọc chuẩn.

Phase 3 cũng có `CSVProvider` cho file được cung cấp rõ ràng và `MockProvider` cho test xác định. Các interface placeholder cho TradingView market data, Polygon, MT5, broker và exchange không chứa logic kết nối hoặc thực thi lệnh.

Khả năng có volume FX và độ sâu lịch sử phụ thuộc provider/gói thuê bao. Volume thiếu vẫn là `null`, không được bịa. `MT5MarketDataProvider` read-only là ranh giới tích hợp tương lai và không có phương thức thực thi.
