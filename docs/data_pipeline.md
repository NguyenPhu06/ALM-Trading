# Pipeline market intelligence lịch sử

Pipeline lịch sử của Phase 3:

```text
provider rows
  -> hợp đồng chuẩn hóa
  -> kiểm tra toàn batch
  -> upsert theo source trong transaction
  -> chọn MTF native / resample bucket hoàn chỉnh
  -> tính feature nhân quả tại as_of
  -> market intelligence snapshot
  -> lưu database có version
```

`MarketDataProvider` giúp consumer không phụ thuộc adapter cụ thể. `CSVProvider` đọc file cục bộ được cho phép, còn `MockProvider` nhận các hàng xác định do caller cung cấp để test. Các lớp MT5, broker, TradingView market data, exchange và Polygon chỉ là interface read-only chưa kết nối. Hệ thống không scrape TradingView.

Pipeline kiểm tra toàn bộ batch được yêu cầu trước một lần upsert, từ chối symbol/timeframe không khớp, đảm bảo tính duy nhất theo source, loại candle chưa hoàn tất khỏi feature và bỏ bucket resampling không đầy đủ. Dữ liệu mẫu `local_csv` không phải nguồn intelligence production.

Mô phỏng backtest sử dụng snapshot thông qua strategy contract. DCA là mô phỏng có ràng buộc, không phải logic cứu lệnh, và không thể vượt giới hạn số điểm vào, mức phơi nhiễm, khoảng cách bất lợi, drawdown hoặc thời gian. Bản ghi kiểm toán giao dịch mô phỏng giữ thời điểm/giá vào ra, hướng, size, PnL, drawdown, lý do, các entry, lần đánh giá và cờ giao dịch ngược xu hướng.
