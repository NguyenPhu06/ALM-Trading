# Orchestration loop

Phase 9 bổ sung vòng lặp nhỏ nhất để các thành phần đã có chạy end-to-end. Trước đó strategy engine, inference engine và paper service chỉ được gọi từ test, nên mọi panel dashboard phía sau strategy luôn rỗng.

## Một tick

```
provider/data → validation → market snapshot → intelligence
   → optional AI inference → strategy evaluation → risk gate
   → paper execution → persistence → alerts → dashboard
```

`OrchestrationCycle.run(symbol)` thực hiện đúng một tick cho một symbol và trả về `CycleResult` gồm stage, reason codes, data quality, provider status, model status, decision và kết quả paper execution.

`OrchestrationRunner` lặp `tick()` theo `interval_seconds`, mỗi tick một session, và giữ bộ nhớ giữa các tick để không đánh giá lại cùng một nến đã đóng.

## An toàn

- Chỉ dùng nến ĐÃ ĐÓNG. `RealMarketSnapshotEngine` loại nến chưa đóng và nến có timestamp sau `as_of`; `MarketIntelligenceService` truy vấn với `closed_only=True`. Vòng lặp không tự tạo nguồn nến nào.
- Không có dữ liệu tương lai. Strategy engine raise nếu timeframe state hoặc prediction có timestamp sau snapshot; paper execution từ chối order có `source_timestamp` sau thời điểm thực thi.
- Không có broker route. Lời gọi thực thi duy nhất là `PaperTradingService`, với `EnvironmentSafetyLock` từ chối mọi environment khác `PAPER`.
- Không bịa AI. Khi chưa có model đã train, cycle truyền `prediction=None`; risk gate hiện có phát `MODEL_UNAVAILABLE`, setup thành `INVALID` và không có entry. Không thay thế bằng giá trị mặc định, prior hay ngẫu nhiên.
- Một nến chỉ được đánh giá một lần, và vòng lặp không mở thêm vị thế thứ hai trên cùng symbol.

## Cấu hình

`config/settings.yaml`, khối `phase_9.orchestration`:

| Khóa | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `enabled` | `false` | Vòng lặp là opt-in. Khởi động API không tự khởi động hoạt động giao dịch. |
| `symbols` | `[EURUSD]` | Danh sách symbol mỗi tick duyệt qua. |
| `interval_seconds` | `60` | Khoảng cách giữa hai tick. |
| `fixed_position_size` | `0.1` | Kích thước lệnh paper, đi qua `PositionSizingEngine`. |
| `model_version` | `null` | Model trong registry. `null` giữ nguyên hành vi model-unavailable. |
| `model_registry_path` | `data/models` | Thư mục registry bất biến. |
| `restore_paper_state_on_start` | `true` | Nạp lại paper state từ database khi API khởi động. |

## Chạy

```text
python -m scripts.run_orchestrator --once
python -m scripts.run_orchestrator --symbol EURUSD --ticks 10 --interval 60
```

`--once` và `--enable` cho phép chạy thủ công ngay cả khi `enabled: false`. Khi bật `enabled: true`, API khởi động vòng lặp nền và dừng nó khi shutdown.
