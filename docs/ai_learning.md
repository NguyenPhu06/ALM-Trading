# AI Learning — Phase 13

Phase 13 dựng vòng học **forward-only**:

```
OBSERVE -> LABEL -> DATASET -> TRAIN -> VALIDATE -> COMPARE -> REGISTER
```

Đây **không** phải `OBSERVE -> TRAIN -> TRADE`. Không bước nào trong chuỗi trên dẫn tới việc gửi order.

## Bốn nguyên tắc

1. **Học tách rời khỏi giao dịch.** Training chỉ chạy qua job tường minh (`scripts/train_forward_model.py`). Không có `model.fit()` nào nằm trong observation loop — `test_online_learning_is_structurally_disabled` parse source của `ObservationCycle` để chứng minh điều đó.
2. **Model chỉ cung cấp xác suất.** Neural network không tạo `BUY`/`SELL`, không chạm Risk Engine, Execution Guard hay kill switch. Nó là **một** thành phần có trọng số trong Strategy Engine (`nn_alignment < 0.5`).
3. **Không tự động thăng hạng.** `AI_AUTO_PROMOTE=false` được validator ở `config/settings.py` ép cứng: bật lên thì process không khởi động được.
4. **Không có online learning.** `AI_ONLINE_LEARNING_ENABLED=false`, cũng ép cứng theo cách tương tự.

## Trạng thái an toàn không đổi sau Phase 13

| Cờ | Giá trị |
| --- | --- |
| `LIVE_TRADING_ENABLED` | `false` |
| `DEMO_TRADING_ENABLED` | `false` |
| `MT5_EXECUTION_ENABLED` | `false` |
| `EXECUTION_KILL_SWITCH` | `true` |
| `OBSERVATION_MODE` | `true` |

`tests/test_strategy_nn_integration.py` khẳng định rằng training một model **không** đặt order, không sửa tài khoản MT5, không bật execution, không hạ kill switch và không đổi trading environment. Promotion cũng vậy.

## Ranh giới kiến trúc

```
MT5 (read-only) -> Feature Extractor -> Neural Network -> Strategy Engine
                                                       -> Risk Engine
                                                       -> Execution Guard
                                                       -> Observation (ZERO orders)
```

`test_no_ai_module_references_execution` quét toàn bộ package `ai/` bằng AST và từ chối mọi tham chiếu tới `MT5ExecutionClient`, `send_market_order`, `order_send`, `ExecutionGuard`, `ExecutionKillSwitch`, `PaperTradingService` hoặc `execution.mt5`.

Xem thêm: [dataset_pipeline.md](dataset_pipeline.md), [walk_forward_validation.md](walk_forward_validation.md), [champion_challenger.md](champion_challenger.md), [model_drift.md](model_drift.md), [ai_explainability.md](ai_explainability.md).
