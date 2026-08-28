# Market Snapshot API

## GET /market/snapshot

Trả một view thị trường thống nhất tại thời điểm hiện tại.

| Query | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `symbol` | `phase_12.symbols[0]` | symbol cần xem |
| `refresh` | `false` | `true` chạy một observation cycle mới |

`refresh=false` trả snapshot đã lưu gần nhất, nên dashboard poll không chạy lại toàn bộ pipeline.

## Nội dung

`timestamp`, `symbol`, `price` (bid/ask/mid), `spread`, `sessions`, `regime` (kèm điểm HTF/LTF và conflict), `timeframes` D1→M5, `structure`, `liquidity` (tách OBSERVED/INFERRED), `indicators`, `neural_network`, `strategy`, `risk`, `execution`, `data_quality`, `source`, `cycle_id`.

Luôn kèm `orders_sent: 0` và `observation_mode`.

## GET /system/health

Từng component báo `HEALTHY` / `DEGRADED` / `FAILED` / `UNKNOWN`:

`api`, `database`, `mt5`, `market_data`, `data_quality`, `strategy`, `nn`, `risk`, `execution`, `dashboard`, `monitoring`.

`UNKNOWN` được xếp **nặng hơn** `DEGRADED`: một component không quan sát được nguy hiểm hơn một component đã biết là suy giảm. Component không báo cáo giữ nguyên `UNKNOWN`, không bao giờ được mặc định là healthy.

Trạng thái tổng là trạng thái xấu nhất trong các component.
