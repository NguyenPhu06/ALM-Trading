# Dataset ML Phase 4

Phase 4 xây dựng dataset nghiên cứu bất biến và có thể tái lập từ candle thị trường lịch sử đã đóng. Phase này không train model và không tạo trading signal.

## Pipeline

`raw -> validation -> chuẩn hóa UTC -> loại duplicate xác định -> căn theo close time -> resampling MTF -> indicator -> structure -> liquidity -> snapshot -> feature -> label -> chia theo thời gian -> chuẩn hóa fit trên TRAIN -> Parquet`

Symbol ban đầu là EURUSD. Kiến trúc chấp nhận EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD và XAUUSD. Timestamp dataset là thời điểm đóng M15. Trạng thái D1, H4, H1, M30, M15 và M5 được chọn độc lập theo `candle_close_time <= T`; M5 không bao giờ được tạo giả từ M15.

Feature schema `phase4.features.v1` có 58 trường số: availability, trend, structure, ATR, ADX và RSI theo timeframe; trạng thái Ichimoku HTF; khoảng cách liquidity và sweep; BOS/CHoCH và HH/HL/LH/LL; volatility; session; weekday/hour/minute/even-hour. Giá trị thiếu được mã hóa rõ bằng availability field và production build mặc định từ chối lịch sử timeframe/indicator không đầy đủ.

Label schema `phase4.labels.v1` có future return sau 1/3/5/10 candle M15, MFE, MAE, classification và outcome nghiên cứu long/short. Label không phải quyết định giao dịch.

Chạy:

```text
python scripts/build_ml_dataset.py --symbol EURUSD
python scripts/check_ml_dataset.py
```

Artifact được ghi dưới `data/ml/` bằng dataset ID bất biến và bị Git ignore. Build giống hệt sẽ tái sử dụng artifact khớp; nội dung xung đột không bao giờ bị ghi đè. Metadata lưu khoảng dữ liệu, ranh giới split theo thời gian, schema hash, content hash, version feature/label, trạng thái scaler, báo cáo chất lượng và thống kê mô tả.

Production readiness mặc định yêu cầu ít nhất 1.000 sample hoàn chỉnh. Thiếu lịch sử M5/MTF thật dẫn đến `DATASET NOT READY`; dữ liệu sample/test bị loại trừ trừ khi được yêu cầu rõ ràng.
