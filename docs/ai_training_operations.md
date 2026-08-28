# AI Training Operations — Phase 14

Training là một **job**, không phải một hệ quả. Không có gì trong vòng quan sát 24/7 fit được model.

## Trigger đề xuất, người quyết định

| Trigger | Mặc định |
| --- | --- |
| `manual_training` | **true** |
| `automatic_training` | **false** (bị validator chặn lúc khởi động) |
| `minimum_new_observations` | 500 |
| `scheduled_training` | false |
| `drift_detected` | true |
| `performance_degradation` | 0.10 |

`TriggerDecision.may_start_automatically` là hằng `False`, và `requires_human` là hằng `True`. Cờ `automatic_training` **không đọc từ YAML** — nó đọc từ `Settings`, và `AI_AUTOMATIC_TRAINING=true` khiến process không khởi động được. Sửa YAML không mở được cổng này.

## Job

```bash
python -m scripts.train_forward_model            # Phase 13 CLI
```

`TrainingJob` (`ai/training/train.py`) là đường duy nhất fit model. Nó raise `OnlineLearningRefused` nếu `AI_ONLINE_LEARNING_ENABLED` bật, và trả `JobResult` với `orders_sent = 0`, `promoted = False`.

## Mười bước

`TrainingPipeline` (`ai/training/pipeline.py`):

```
LOAD -> VALIDATE -> LEAKAGE -> SPLIT -> PREPROCESS
     -> TRAIN -> EVALUATE -> COMPARE -> REPORT -> REGISTER
```

Bước 1–5 do `DatasetBuilder` thực hiện trong một lượt, nhưng pipeline vẫn ghi từng bước riêng — để một thất bại nói rõ **giai đoạn nào** từ chối, thay vì một chữ "dataset invalid" mù mờ.

`PREPROCESS` khẳng định scaler được fit trên `TRAIN` (`ScalerState.fitted_split`). `SPLIT` khẳng định timestamp cuối của TRAIN nhỏ hơn timestamp đầu của TEST.

**Không có bước 11.** `PipelineReport.promoted` là hằng `False`. Thăng hạng cần `POST /ai/models/{model_id}/approve` với một người có tên.

## Đánh giá challenger

`ChallengerEvaluator` (`ai/training/evaluation.py`) tách khỏi code sinh model — thứ tạo ra model không nên là thứ phán model tốt hay không. Ba câu hỏi, theo thứ tự:

1. Đánh giá có đáng tin không? (out-of-sample, đủ mẫu, không leakage)
2. Có vượt baseline không? (hoà **không** phải thắng)
3. Có vượt champion không? (chỉ trên tiêu chí out-of-sample)

Verdict: `PROMOTABLE`, `NOT_PROMOTABLE`, `INSUFFICIENT_EVIDENCE`. `promoted` luôn `False`.

## Bảng training_runs

Mỗi lần chạy ghi một dòng: dataset id, trigger, người yêu cầu, bước thất bại (nếu có), edge verdict, đã đăng ký chưa — và cột `promoted` luôn `false`, để bản ghi tự nói ra bảo đảm đó.

Xem thêm: [forward_learning.md](forward_learning.md), [champion_challenger.md](champion_challenger.md), [model_drift.md](model_drift.md), [ai_learning.md](ai_learning.md).
