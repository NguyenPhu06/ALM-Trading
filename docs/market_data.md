# Engine dữ liệu thị trường thật

Phase 2 biến candle đã chuẩn hóa trong database thành đầu vào chuẩn cho feature, market regime và backtest. Hệ thống hỗ trợ `EURUSD`, `GBPUSD`, `USDJPY`, `USDCHF`, `AUDUSD`, `USDCAD`, `NZDUSD` và `XAUUSD` tại `M1`, `M5`, `M15`, `M30`, `H1`, `H4`, `D1`. Các danh sách này là cấu hình, không phải quy tắc strategy.

Mọi timestamp đều có timezone và ở UTC. Candle lưu source, provider, provider timestamp, ingestion time và trạng thái đóng. Định danh database là `(symbol, timeframe, timestamp, source)`, nên import lặp lại có tính idempotent trong khi các nguồn được cấp phép độc lập vẫn có thể cùng tồn tại.

## Import lịch sử

Cấu hình `MARKET_DATA_API_KEY` trong `.env`, sau đó chạy import có giới hạn:

```text
python -m scripts.import_market_data --provider historical --symbol EURUSD --timeframe M15 --start 2025-01-01 --end 2025-02-01
```

Chỉ cập nhật từ sau candle provider mới nhất đã lưu:

```text
python -m scripts.update_market_data --provider historical --symbol EURUSD --timeframe M15
```

Import kiểm tra toàn bộ response trước một transactional upsert. Request provider thất bại hoặc batch sai không thể thay thế một phần candle hiện có. Bản ghi kiểm toán trong `market_data_ingestions` chứa số lượng, thời gian chạy, gap, trạng thái và loại lỗi đã loại thông tin nhạy cảm.

## API

- `GET /api/market-data/candles`: hỗ trợ symbol, timeframe, start, end, source, closed state, limit và offset.
- `GET /api/market-data/latest`: trả candle phù hợp mới nhất.
- `GET /api/market-data/health`: trả số lượng, timestamp mới nhất, freshness, trạng thái và gap gần đây.
- `GET /api/market-data/gaps`: trả gap gần đây có ý nghĩa trong giờ thị trường.
- `GET /api/market-data/providers`: trả health cấu hình/kiểm toán mà không lộ secret.
- `GET /api/market-data/readiness`: kiểm tra toàn bộ symbol và timeframe đã cấu hình.

## Dữ liệu mẫu và dữ liệu thật

`data/sample/EURUSD_M15_sample.csv` là **dữ liệu mẫu** xác định dùng cho unit test và minh họa cục bộ. Đây không phải nguồn Phase 2 mặc định và không được mô tả như lịch sử thị trường thật. Source `local_csv` bị loại khỏi kiểm tra health/readiness dữ liệu thật. Dữ liệu thật đi qua provider đã cấu hình và giữ provenance của provider.

Subsystem này chỉ tạo dữ liệu. Nó không có đường dẫn đến `BUY`, `SELL`, DCA, broker execution hay live order.
