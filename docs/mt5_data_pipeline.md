# MT5 Data Pipeline

## Luồng

```
MT5 terminal
   ↓  MT5ReadOnlyClient (read-only)
MT5 Adapter          execution/mt5/market_data.py
   ↓  CandleNormalizer / QuoteNormalizer
Market Data Model    schema chung của ALM
   ↓  MT5DataQualityGate
Feature Engine → Liquidity / Structure / Indicators → Market Intelligence
   ↓
Neural Network (nếu có model)
   ↓
Strategy Engine → Risk Gate
   ↓
PAPER TRADING          ← execution dừng ở đây
```

Strategy không bao giờ chạm vào object MetaTrader5, numpy record hay tên symbol của broker. Mọi thứ rời khỏi adapter đều là dict ALM chuẩn.

## Normalization

`MT5MarketDataReader` chuyển:

- `time` (epoch giây) → `datetime` UTC
- tên broker → tên canonical
- record numpy → dict

Mỗi candle có: `timestamp`, `open`, `high`, `low`, `close`, `volume`, `tick_volume`, `spread`, `symbol`, `timeframe`, `source`, `is_closed`, `provider`, `provider_timestamp`.

Chỉ nến ĐÃ ĐÓNG được trả về: bar chưa hết chu kỳ bị loại (`opened + delta > now`).

## Multi-timeframe

Bắt buộc đủ **D1, H4, H1, M30, M15, M5** — không chỉ M15.

```python
client.get_multi_timeframe_rates("EURUSD")     # dict[timeframe, ReadResult]
service.multi_timeframe("EURUSD")              # payload dashboard kèm data age
```

## Data quality

`MT5DataQualityGate` dùng lại `MarketQualityValidator` chung, cộng thêm kiểm tra riêng cho feed broker:

| Kiểm tra | Mã |
| --- | --- |
| Giá âm hoặc bằng 0 | `NON_POSITIVE_PRICE` |
| Timestamp trùng | `DUPLICATE_TIMESTAMP` |
| Lệch biên timeframe | `TIMEFRAME_MISALIGNED` |
| Symbol lạ | `UNKNOWN_SYMBOL` |
| Tick quá cũ | `STALE_TICK` |
| OHLC mâu thuẫn, thiếu nến, gap | từ validator chung |

Kết quả `INVALID` → `DATA_QUALITY_ERROR`, batch bị loại bỏ hoàn toàn và **không có nến nào đi tiếp** vào feature/strategy. Mỗi lần đánh giá ghi một dòng vào `mt5_data_quality_events`.

## Freshness

Mỗi timeframe báo `last_candle` và `data_age_seconds` thật. Tick có ngưỡng riêng (`phase_10.tick_stale_seconds`, mặc định 30s). Dữ liệu stale không được dùng để tạo entry signal.

## Spread monitoring

`SpreadMonitor` giữ cửa sổ trượt và phân loại `NORMAL` / `ELEVATED` / `EXTREME` theo tỉ lệ so với trung bình. Phase 10 chỉ **ghi nhận** trạng thái; `blocks_new_entry` được tính nhưng chưa có lệnh nào để chặn.

## Source comparison

`compare_sources()` so sánh giá, spread và timestamp giữa MT5 và provider khác. Vượt ngưỡng → `DATA_SOURCE_DISCREPANCY`. Chỉ cảnh báo, không trade.

Mọi payload đều mang `source`, nên dữ liệu từ nhiều nguồn không bao giờ bị trộn mà không ghi rõ nguồn.

## Vào pipeline hiện có

`MT5MarketDataProvider` implement `BaseMarketDataProvider`, nên MT5 dùng chung đường ingestion/quality/snapshot với mọi provider khác:

```python
provider = create_provider("mt5")
MarketDataIngestionService(session, provider).import_historical("EURUSD", "M15", start, end)
```
