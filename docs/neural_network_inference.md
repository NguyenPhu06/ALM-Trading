# Neural Network Inference (Phase 12)

## Ranh giới

NN chỉ sinh xác suất. Nó **không** được đặt lệnh, không được bỏ qua risk, và không được retrain trong lúc quan sát thị trường thật.

`NeuralInferenceEngine` chỉ có ba method công khai: `predict`, `model_input`, `decision_context`. Test khẳng định không tồn tại `send_order`, `execute`, `order_send`, `place_order`, `submit`.

## Output

`prob_up`, `prob_down`, `prob_neutral`, `confidence`, `model_version`, `feature_version`, `timestamp`.

Timestamp bắt buộc timezone-aware; xác suất bắt buộc trong `[0, 1]`.

## Quy tắc an toàn

- **Không có model → không thay thế.** Cycle truyền `prediction=None`; risk gate hiện có phát `MODEL_UNAVAILABLE` và không có entry. Không dùng giá trị mặc định, prior hay ngẫu nhiên.
- **Prediction tương lai bị loại.** Nếu `prediction.timestamp > snapshot.timestamp`, cycle bỏ nó và ghi `MODEL_RETURNED_FUTURE_PREDICTION`.
- **Model lỗi không làm sập cycle.** Exception được bắt, ghi alert `MODEL_ERROR`, `nn` báo `FAILED`, cycle tiếp tục nhưng không có NN input.
- **Không tự retrain.** Không có đường nào trong Phase 12 ghi đè file model production.

## Trong feature snapshot

Output NN được lưu kèm `model_version` và `feature_version`, nên dữ liệu quan sát về sau truy được nguồn gốc model đã sinh ra nó.
