# Nguồn dữ liệu và ngữ nghĩa

ALM phân biệt quan sát theo độ trễ và cách suy diễn để nghiên cứu sau này không vô tình coi dữ liệu chậm hoặc dữ liệu suy ra là sự thật thời gian thực.

| Nguồn/dữ liệu | Phân loại | Ý nghĩa |
|---|---|---|
| TradingView webhook | Vận chuyển sự kiện REAL-TIME | Dữ liệu cảnh báo/sự kiện do logic TradingView đã cấu hình tạo ra; không phải tick feed hoàn chỉnh. |
| Market tick (adapter tương lai) | REAL-TIME | Quan sát được cấp phép từ broker/exchange khi triển khai. |
| CFTC TFF COT | PERIODIC | Vị thế tổ chức báo cáo hàng tuần, thường phản ánh vị thế thứ Ba và được công bố sau đó. |
| Candle CSV cục bộ | HISTORICAL | Dữ liệu OHLCV mẫu/import có thể tái lập. |
| Candle broker/MT5/futures/exchange (tương lai) | REAL-TIME hoặc HISTORICAL | Phân loại phụ thuộc endpoint được cấp phép và chế độ request. |
| Tin tức (tương lai) | REAL-TIME hoặc HISTORICAL | Nội dung có timestamp từ provider; phải lưu độ trễ nguồn. |
| Open interest và volume (tương lai) | PERIODIC hoặc REAL-TIME | Quan sát phụ thuộc provider; phải mô tả ngữ nghĩa và độ trễ cho từng adapter. |
| Sự kiện liquidity/structure | INFERRED | Ước lượng cấu trúc thị trường do ALM suy ra, không phải lệnh thật của tổ chức. |
| Institutional pressure | INFERRED | Ước lượng tổng hợp từ đầu vào công khai hoặc được cấp phép; đầu vào thiếu giữ nguyên `NULL`. |

## Giới hạn của CFTC COT

COT là dữ liệu vị thế định kỳ, không phải dòng lệnh tổ chức thời gian thực hay “lệnh cá voi thời gian thực”. Collector Phase 1A dùng feed CFTC TFF Futures Only chính thức vì các nhóm Dealer, Asset Manager, Leveraged Money, Other Reportables và Non-Reportables phù hợp model database. Parser có cấu hình chấp nhận định dạng text tuần không header chính thức cũng như bản xuất CSV/JSON. Hàng nguồn thô được giữ lại. Feature phải tôn trọng độ trễ công bố, bản sửa đổi, ánh xạ market sang FX symbol và phép tổng hợp để tránh look-ahead bias.

ALM chỉ ước lượng vị thế hoặc áp lực tổ chức bằng dữ liệu công khai/được cấp phép hiện có. Hệ thống không thể biết quỹ cụ thể nào đang mua một cặp FX.

## Xác thực webhook

Cơ chế ưu tiên là header `X-TradingView-Secret` với phép so sánh constant-time. Nếu cấu hình alert không gửi được header, trường JSON `secret` có thể được chấp nhận khi được bật. Cách dự phòng này làm credential đi qua nhiều hệ thống hơn; cần dùng HTTPS, giá trị ngẫu nhiên dài, xoay vòng secret và giới hạn ingress. Trường `secret` bị loại trước khi lưu payload thô để kiểm toán và không bao giờ được log.

URL CFTC có thể cấu hình trong `config/settings.yaml`. Nếu tương lai chuyển sang SODA API, `X-App-Token` phải lấy từ secret môi trường thay vì ghi trực tiếp trong cấu hình.

## Adapter tương lai

`MarketDataProvider` định nghĩa thao tác đọc candle/latest cho Local CSV, MT5, broker và exchange tương lai. `future_interfaces.py` định nghĩa contract read-only cho futures, news, open interest, volume và order book. Phase 1A không có kết nối live hay phương thức đặt lệnh. Mỗi adapter tương lai phải thực hiện raw → normalize → validate → repository, xác định nguồn và license, dùng UTC, giữ dữ liệu thô cần thiết, công bố độ trễ và từ chối quan sát sai định dạng.
