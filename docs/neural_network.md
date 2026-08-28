# Neural Network Research Engine

Phase 5 cung cấp một mạng MLP ba lớp đầu ra được viết bằng NumPy cho nghiên cứu xác suất `UP`, `DOWN` và `NEUTRAL`. Tổng ba xác suất luôn bằng 1. Model không tạo `BUY`, `SELL`, position hay order.

Đầu vào là 58 feature MTF có version từ dataset Phase 4. `ModelInput` chỉ chứa timestamp, symbol, feature values/names, feature version và dataset version; constructor từ chối tên trường label, future return, MFE hoặc MAE.

Architecture dùng số hidden layer, hidden unit, dropout, learning rate, batch size, epoch, early stopping và random seed trong `config/settings.yaml`. Batch TRAIN được xử lý theo thứ tự, không shuffle giữa các giai đoạn. Mean/std đã được fit trên TRAIN ở Phase 4 và cùng scaler bất biến được dùng khi inference.

Training luôn so sánh với ba baseline: majority class, softmax logistic regression và decision stump. Không giả định Neural Network tốt hơn. Nếu balanced accuracy của model không vượt baseline tốt nhất, báo cáo phải ghi `NEURAL NETWORK DOES NOT BEAT BASELINE`.

Hiện database production chưa có dataset Phase 4 đạt readiness, vì vậy `scripts/train_model.py` từ chối training thay vì dùng dữ liệu sample hoặc fixture.

## Phase 13 — multi-task network

Phase 13 bổ sung `MultiTaskMLP` (`ai/models/multitask.py`) bên cạnh mạng nghiên cứu Phase 5. Mạng này có bốn đầu ra học đồng thời từ **141 feature** `features_v1`:

| Head | Kiểu | Ý nghĩa |
| --- | --- | --- |
| direction | softmax 3 lớp | `UP` / `DOWN` / `NEUTRAL` |
| expected return | regression | return kỳ vọng theo horizon |
| expected MFE | regression | biến động thuận lợi tối đa kỳ vọng |
| expected MAE | regression | biến động bất lợi tối đa kỳ vọng |
| volatility | sigmoid | mức biến động kỳ vọng |

Đầu vào **phải** đã được scale bằng đúng scaler đã fit trên TRAIN. `_check_scaling()` so độ lớn đầu vào với `SCALE_TOLERANCE = 10.0`; nếu nghi ngờ dữ liệu chưa scale, cảnh báo được ghi vào `TrainingHistory.input_scaled` và `TrainingHistory.warnings` thay vì để model học lặng lẽ trên thang sai. Đây là lỗi đã thực sự xảy ra khi phát triển: cùng một vòng training cho accuracy 0.27 với feature thô và 0.81 với feature đã scale.

`MultiTaskInferenceEngine` (`ai/inference/multitask_engine.py`) là đường inference duy nhất. Nó **không có** `fit`, `train`, `partial_fit`, `update` hay `learn`; `InferenceResult.is_trade_instruction` luôn là `False`, và payload không chứa `buy`, `sell`, `order` hay `action`. Ngưỡng tin cậy nằm trong `phase_13.thresholds`, được trả kèm mỗi prediction chứ không hard-code.

Training chỉ chạy qua `scripts/train_forward_model.py`. Job kết thúc bằng dòng `NOT PROMOTED. Promotion requires POST /ai/models/{id}/approve`.

Xem thêm: [ai_learning.md](ai_learning.md), [dataset_pipeline.md](dataset_pipeline.md), [champion_challenger.md](champion_challenger.md).
