# Forward Learning — Phase 14

Phase 13 dựng vòng học. Phase 14 làm cho nó chạy liên tục.

```
OBSERVE -> LABEL -> DATASET -> TRAIN -> VALIDATE -> COMPARE -> REGISTER
   ^                                                              |
   +---------------- chạy 24/7, không bao giờ gửi order ----------+
```

## Vòng đời một observation

```
CREATED -> FEATURES_CAPTURED -> NN_PREDICTED -> STRATEGY_EVALUATED
        -> RISK_EVALUATED -> OBSERVING -> HORIZON_REACHED
        -> OUTCOME_CALCULATED -> LABELED -> DATASET_READY
```

Trạng thái lỗi (terminal, không bao giờ quay lại): `DATA_INVALID`, `MODEL_ERROR`, `CALCULATION_ERROR`, `TIMEOUT`.

Máy trạng thái chỉ tiến **một bước một lần**. Nhảy cóc, lùi lại hay lặp một bước đều raise `LifecycleError`. Điều đó nghĩa là một crash giữa chừng để lại bản ghi **có thể tiếp tục**, không phải bản ghi mơ hồ.

## Kết quả forward

`ForwardOutcomeEngine` chỉ trả lời **sau khi** horizon trôi qua. Nó từ chối khi:

| Lý do | Ý nghĩa |
| --- | --- |
| `HORIZON_NOT_REACHED` | `now` chưa tới deadline, hoặc cửa sổ nến không chạm deadline |
| `NO_FUTURE_DATA` | không có nến nào trong cửa sổ |
| `NO_ENTRY_PRICE` | observation không có giá vào |
| `NOT_DIRECTIONAL` | tín hiệu là WAIT, không có gì để đo |
| `UNKNOWN_HORIZON` | horizon không nằm trong `HORIZONS` |

### `future_return` và `actual_direction` không cùng dấu

`future_return` được ký theo **hướng đã quan sát**: một lệnh SELL có lãi mang return dương dù thị trường đi xuống. Suy hướng thị trường từ dấu của return sẽ gọi mọi SELL thắng là "thị trường UP" và đánh dấu nó là dự đoán sai. Vì vậy `actual_direction` được tính từ **chuyển động giá thô** (`future_price - entry_price`), còn `predicted_direction` ánh xạ BUY→UP, SELL→DOWN. Đây là một lỗi thật đã bị bắt trong lúc phát triển.

## Chi phí thật

Mọi con số hiệu năng là **net**. `net_hypothetical_pnl = future_return - (spread + commission + slippage + swap) / entry_price`.

Một chuyển động gộp dương nhưng nhỏ hơn chi phí là **lỗ**, không phải "lãi nhỏ" — `test_a_move_that_does_not_clear_costs_is_not_profitable` khẳng định đúng điều đó. Swap tích luỹ theo thời gian nắm giữ.

## Vào dataset

`DatasetIngestor` là cổng giữa observation đã có nhãn và dataset học. Nó kiểm ba version (`features_v1` / `labels_v1` / `scaler_v1`), từ chối dòng đã thấy, và báo cáo lý do thay vì raise:

`NOT_LABELED`, `MISSING_LABEL`, `DUPLICATE_ROW`, `FEATURE_VERSION_MISMATCH`, `LABEL_VERSION_MISMATCH`, `NO_ENTRY_PRICE`.

Nếu ghi thất bại, dòng **không** bị đánh dấu đã thấy — để lần sau còn thử lại được.

## Học không xảy ra ở đây

`ai/training/` là nơi duy nhất fit model, và chỉ qua job tường minh. Không module nào trong `observation/` import `ForwardTrainer`, `TrainingJob`, `TrainingPipeline` hay `MultiTaskMLP`; `tests/test_training_isolation.py` parse import graph để chứng minh.

Xem thêm: [observation_driver.md](observation_driver.md), [ai_training_operations.md](ai_training_operations.md), [statistical_edge.md](statistical_edge.md), [ai_learning.md](ai_learning.md).
