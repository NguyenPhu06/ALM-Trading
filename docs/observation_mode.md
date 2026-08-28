# Observation Mode

`OBSERVATION_MODE=true` là mặc định của Phase 12. Hệ thống quan sát thị trường thật, tính toàn bộ tín hiệu, và **gửi ZERO lệnh**.

## Nó tính gì

- market data D1→M5 từ MT5
- data quality gate
- market structure, liquidity, indicators, session
- unified market regime
- neural network probability (nếu có model)
- strategy decision + risk state
- vị thế giả định, DCA giả định, exit giả định, PnL giả định

## Nó không làm gì

Không gửi order. Không sửa order. Không đóng position. Không DCA thật.

Tầng cuối của mỗi cycle là `ExecutionSimulator`, module này **không có transport nào** — không `order_send`, không HTTP client, không socket. Test `test_the_simulator_has_no_transport` kiểm tra bằng cách parse source.

## Vì sao observation mode là lớp bảo vệ ngoài cùng

Ngay cả khi **mọi cổng Phase 11 đều mở** (`DEMO_TRADING_ENABLED=true`, `MT5_EXECUTION_ENABLED=true`, kill switch nhả), observation mode vẫn chặn:

```
SIGNAL = BUY
RISK = APPROVED
EXECUTION = BLOCKED
REASON = OBSERVATION_MODE_ACTIVE
```

Test `test_even_with_every_flag_open_observation_mode_still_blocks` khẳng định điều này.

## Dữ liệu thu được

Mỗi cycle ghi:

- `feature_snapshots` — bản ghi đầy đủ, dùng làm training data về sau
- `observation_market_snapshots` — view thị trường tại thời điểm đó
- `execution_simulations` — `orders_sent` luôn bằng 0
- `system_health` — trạng thái từng component
- `observation_performance` — forward observation: signal, entry, exit giả định, MAE, MFE, PnL giả định, spread, session, regime, confidence, DCA state

`observation_performance` **không phải backtest**. Đây là dữ liệu quan sát tiến về phía trước, thu thập trên thị trường thật, chưa từng có lệnh nào được đặt.

## Chạy

```text
POST /observation/cycle?symbol=EURUSD     chạy một cycle
GET  /observation/status                  trạng thái + simulation gần đây
GET  /observation/performance             forward observation data
GET  /market/snapshot?refresh=true        chạy cycle và trả snapshot
```
