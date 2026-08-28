# Observation Driver — Phase 14

`observation/driver.py` là thành phần duy nhất trong hệ thống được thiết kế để chạy hàng tuần liền. Việc của nó: giữ cho cycle Phase 12 nổ đúng lịch, giải quyết observation khi horizon trôi qua, và sống sót qua restart mà không nhân đôi bất cứ thứ gì.

```
tick -> deterministic cycle_id -> đã chạy chưa? -> chạy cycle
     -> ghi observation -> giải quyết observation đến hạn -> health
```

Driver **không** cầm execution client, **không** gửi order, **không** sửa position MT5 và **không** hạ được kill switch. `test_the_driver_holds_no_execution_client` kiểm tra bằng cách khẳng định object không có thuộc tính `client`, `broker`, `execution`, `guard` hay `kill_switch`.

## Lịch chạy

Chỉ năm interval được chấp nhận (`ALLOWED_INTERVALS`): **60, 300, 900, 1800, 3600** giây. Mặc định là **300** (5 phút), lấy từ `phase_14.interval_seconds`. Một giá trị ngoài danh sách là lỗi cấu hình, và `DriverConfig.from_settings()` raise thay vì làm tròn.

## Idempotency

`cycle_id = sha256(symbol | timeframe | candle_timestamp)[:32]`

`candle_timestamp` được làm tròn xuống lưới interval và chuẩn hoá về UTC, nên cùng một cây nến trong process khác, múi giờ khác, sau restart vẫn cho đúng một id. Chạy lại cùng candle là **DUPLICATE**, không phải observation thứ hai.

`observation_id` dẫn xuất từ `cycle_id` + symbol + horizon, nên cùng một cycle với horizon khác vẫn là hai observation khác nhau.

## Xử lý lỗi

Một cycle raise không giết driver: nó được ghi là cycle thất bại, alert `OBSERVATION_CYCLE_FAILED` được phát, các symbol còn lại vẫn chạy. Sau `max_consecutive_errors` lần lỗi liên tiếp (mặc định 5), loop dừng với state `FAILED` và alert `OBSERVATION_DRIVER_STOPPED`.

Một cycle **halt** (dữ liệu xấu, tài khoản không hợp lệ) là điều kiện thị trường bình thường, không phải lỗi driver: observation được ghi ở trạng thái `DATA_INVALID`.

## Dừng có kiểm soát

`stop()` đặt cờ; tick đang chạy hoàn tất, tick kế tiếp không bắt đầu. `scripts/run_observation_driver.py` gắn `stop()` vào SIGINT và SIGTERM.

## Health

Driver báo cáo theo bộ component Phase 12. Hai điểm đáng chú ý:

- `UNKNOWN` **nặng hơn** `DEGRADED` trong `SEVERITY` — thứ ta không nhìn thấy nguy hiểm hơn thứ ta biết là hỏng. Vì vậy một driver không có repository hoặc không có alert router sẽ báo tổng thể `UNKNOWN`.
- `nn` là `UNKNOWN` khi chưa cycle nào chạy, `DEGRADED` khi cycle chạy mà không có model, `HEALTHY` khi có prediction. Không model là trạng thái **đã biết**, không phải trạng thái không nhìn thấy.

## Chạy

```bash
python -m scripts.run_observation_driver
python -m scripts.run_observation_driver --ticks 1 --dry-run
python -m scripts.run_observation_driver --interval 900 --symbols EURUSD,GBPUSD
```

Script **từ chối khởi động** nếu bất kỳ cổng execution nào đang mở (`_refuse_unless_safe`): live/demo/mt5 execution bật, kill switch nhả, hoặc observation mode tắt.

Xem thêm: [forward_learning.md](forward_learning.md), [monitoring.md](monitoring.md), [observation_mode.md](observation_mode.md).
