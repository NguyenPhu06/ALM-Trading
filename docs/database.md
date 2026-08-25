# Kiến trúc cơ sở dữ liệu

## Vòng đời candle

`market_candles.is_closed` là ranh giới nhân quả của Phase 1B.1. Import CSV lịch sử đặt trường này thành `true`; đầu vào normalizer không có trạng thái đóng rõ ràng mặc định là `false` để bảo vệ trường hợp dữ liệu live/đang hình thành. Migration `20260824_0003` cập nhật các bản ghi lịch sử đã có thành `true`. Structure, liquidity, resampling và snapshot không bao giờ sử dụng candle đang mở.

ALM chỉ dùng một đường ghi dữ liệu do repository kiểm soát: source adapter → parser → normalizer → validator → repository → PostgreSQL. Collector không rải SQL trong các module nguồn. Docker sử dụng PostgreSQL 17 với extension TimescaleDB sẵn có; Phase 1A dùng bảng và index PostgreSQL thông thường nên migration vẫn có tính di động. Việc chuyển bảng dung lượng lớn thành hypertable được hoãn cho đến khi thống nhất chính sách lưu giữ, phân vùng và tính duy nhất.

## Bảng và quan hệ

- `market_candles`: dữ liệu OHLCV đã chuẩn hóa. `(symbol, timeframe, timestamp, source)` là định danh duy nhất và được đánh index.
- `market_ticks`: nơi lưu cho interface tick; chưa kích hoạt ingestion thời gian thực.
- `tradingview_alerts`: các trường cảnh báo đã kiểm tra cùng bản sao payload nguồn để kiểm toán. Trường xác thực bị loại trước khi lưu.
- `liquidity_events`: sự kiện do ALM suy ra như mức swing/equal/session và liquidity sweep.
- `structure_events`: các sự kiện HH, HL, LH, LL, BOS, CHoCH và vô hiệu hóa.
- `indicator_snapshots`: đầu ra của Indicator Engine. Collector không tính indicator.
- `cot_reports`: vị thế CFTC TFF định kỳ, duy nhất theo ngày báo cáo, thị trường, hợp đồng và nguồn; hàng dữ liệu gốc được giữ lại.
- `institutional_pressure`: các ước lượng thành phần có thể là `NULL`. Phase 1A không tạo giá trị.
- `strategy_signals` và `trading_outcomes`: interface tối thiểu cho dataset/label tương lai; không thực thi giao dịch.
- `market_features`, `market_labels`, `dataset_metadata`: feature, label và metadata dataset có version của Phase 4; không sao chép candle gốc.

Các phép nối logic dùng symbol, timeframe và thời điểm sự kiện/báo cáo. Tránh foreign key cứng giữa những quan sát thị trường đến độc lập. `trading_outcomes.signal_id` là tham chiếu logic tương lai và hiện chưa được điền.

## Thời gian và độ chính xác

Mọi timestamp thị trường phải có timezone và được chuẩn hóa sang UTC trước khi kiểm tra. PostgreSQL dùng `TIMESTAMP WITH TIME ZONE`; client phải hiển thị offset rõ ràng. Giá và volume dùng cột số có độ chính xác cố định thay vì số thực nhị phân. Ngày báo cáo COT dùng kiểu ngày vì dữ liệu mang tính định kỳ, không phải intraday.

## Dữ liệu thô, dữ liệu chuẩn hóa và lưu giữ

JSON TradingView thô và hàng CFTC được giữ để kiểm toán; secret không được lưu. Các cột chuẩn hóa có thể truy vấn và đã được kiểm tra. Bản ghi sai bị log và từ chối thay vì tự sửa im lặng. Phase 1A không áp dụng chính sách xóa mặc định. Trước khi kích hoạt production cần chọn chính sách retention, compression, backup và Timescale hypertable/chunk dựa trên dung lượng quan sát được và yêu cầu pháp lý.

Migration được quản lý bằng Alembic (`alembic upgrade head`). Volume `postgres_data` duy trì dữ liệu khi container được tạo lại.
