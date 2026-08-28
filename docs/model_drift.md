# Model Drift

`ai/model_registry/drift.py` theo dõi việc dữ liệu hiện tại trôi khỏi phân phối lúc training.

## PSI

Population Stability Index so histogram feature lúc training với histogram gần đây. Ngưỡng nằm ở `phase_13.drift` trong `config/settings.yaml`.

Ngoài PSI, monitor còn theo dõi: trôi phân phối nhãn, sụt hiệu năng so với mức lúc validate, và lệch calibration.

## Mọi tín hiệu chỉ là cảnh báo

Mỗi tín hiệu drift mang `action = "FLAG_ONLY"`. Drift **không**:

- tự retrain,
- tự hạ champion,
- tự đổi threshold,
- chạm bất cứ cờ execution nào.

Nó ghi một `ModelDriftEventRecord`, hiện lên dashboard ở ô `DRIFT FLAGGED`, và có thể mở một `RetrainingRequest`. Yêu cầu đó mang `auto_trains: False` và `auto_promotes: False` — con người quyết định chạy hay không.

## Chính sách retraining

`RetrainingPolicy` (`ai/training/retraining.py`) mô tả **khi nào nên xem xét** retrain: đủ số observation mới, drift vượt ngưỡng, hoặc hiệu năng tụt quá mức cho phép. Chính sách chỉ sinh đề xuất; thi hành là job thủ công `scripts/train_forward_model.py`, và model mới ra lò vẫn ở trạng thái `EXPERIMENTAL`.

Xem thêm: [champion_challenger.md](champion_challenger.md), [model_risk.md](model_risk.md).

## Phase 14 — drift trong vòng quan sát 24/7

Vòng 24/7 chạy sáu loại drift qua cùng `DriftMonitor`: feature, prediction, label, performance, regime và session. Kết quả không đổi bản chất: **mỗi tín hiệu chỉ phát alert**.

`tests/test_drift_detection.py` khẳng định điều đó theo hai cách. Về hành vi: chạy `DriftMonitor().evaluate()` với mức sụt hiệu năng cực đoan rồi so lại toàn bộ cờ an toàn — không cờ nào đổi. Về cấu trúc: parse source của `DriftMonitor` và từ chối mọi lần xuất hiện của `ForwardTrainer`, `TrainingJob`, `.fit(`, `promote`, `demote`, `transition`, `kill_switch`, `mt5_execution_enabled`, `order_send`.

Drift phát alert `MODEL_DRIFT` với `context["action"] = "FLAG_ONLY"`, ghi một `ModelDriftEventRecord`, và hiện lên ô `MODEL DRIFT` của dashboard. Nó có thể mở một `RetrainingRequest` — nhưng request đó mang `auto_trains: False` và `auto_promotes: False`, và `TrainingTriggerPolicy` trả `may_start_automatically = False` bất kể có bao nhiêu trigger nổ.

Xem thêm: [ai_training_operations.md](ai_training_operations.md), [observation_driver.md](observation_driver.md).
