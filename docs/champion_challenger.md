# Champion / Challenger

Mỗi `ModelTask` (`task:symbol:timeframe`, ví dụ `direction:EURUSD:M5`) có đúng **một** champion slot.

## Vòng đời

```
EXPERIMENTAL -> VALIDATED -> CANDIDATE -> CHAMPION -> RETIRED
             -> REJECTED
```

`ALLOWED_TRANSITIONS` trong `ai/model_registry/records.py` là bảng chuyển trạng thái duy nhất; mọi bước nhảy khác bị từ chối.

## So sánh

`ChampionChallengerComparator` chấm challenger theo **10 tiêu chí out-of-sample**. Không tiêu chí nào dựa trên metric của tập TRAIN — gồm accuracy và F1 trên TEST, Brier score, log loss, expected calibration error, walk-forward stability, hiệu năng theo regime, hiệu năng theo session, và mức vượt baseline.

Comparator từ chối thẳng challenger đang ở trạng thái `EXPERIMENTAL`: phải `VALIDATED` trước đã.

## Thăng hạng cần con người

`registry.promote()` yêu cầu một `ApprovalToken` mang tên người duyệt và lý do. Không có đường tự động:

- `AI_AUTO_PROMOTE=false` bị validator ép cứng lúc khởi động;
- namespace `/ai` chỉ có đúng hai endpoint ghi: `POST /ai/retraining/request` và `POST /ai/models/{model_id}/approve`. `test_no_api_endpoint_trains_a_model` khẳng định tập này chính xác — không endpoint nào train model;
- promotion không đổi bất kỳ cờ execution nào; kill switch vẫn bật sau khi promote (`test_promotion_cannot_enable_execution`).

## Artifact

Artifact lưu ngoài database, dưới `phase_13.artifacts_path`, không commit vào Git. `scrub_artifact()` xoá mọi key nhạy cảm (`password`, `secret`, `token`, `api_key`, …) ở mọi độ sâu trước khi ghi. Không schema nào trong `model_registry`, `dataset_audits`, `model_drift_events`, `retraining_requests` có cột binary hoặc cột tên chứa credential.

Xem thêm: [model_registry.md](model_registry.md), [model_drift.md](model_drift.md).

## Phase 15 — champion/challenger cho *chiến lược*

Phần trên nói về model. Phase 15 dựng cơ chế song song cho **chiến lược**, với cùng một luật ở cuối: bằng chứng chỉ **đề xuất**, con người mới thăng hạng.

`StrategyChallengerEvaluator` cho challenger đi qua năm cổng, theo thứ tự:

| Cổng | Hỏi gì |
| --- | --- |
| `OUT_OF_SAMPLE` | cả hai phía có phải forward observation không, và có bao nhiêu dòng chung |
| `WALK_FORWARD` | có nhất quán qua các cửa sổ không |
| `SAMPLE_SIZE` | **cả hai** phía có đủ mẫu không |
| `RISK_ADJUSTED` | expectancy tốt hơn **và** drawdown không xấu đi |
| `STABILITY` | có segment nào reliable, và không segment nào lỗ |

Cổng `RISK_ADJUSTED` là nơi phần lớn challenger trượt: lợi nhuận cao hơn kèm hố sâu hơn **không** phải cải thiện. Cổng `STABILITY` bắt trường hợp còn lại — một challenger thắng tổng thể nhưng chỉ nhờ một session.

Bốn verdict: `RECOMMEND_PROMOTION`, `KEEP_CHAMPION`, `REJECT_CHALLENGER`, `INSUFFICIENT_EVIDENCE`. `ChallengerReport.promoted` là hằng `False`, và `StrategyChallengerEvaluator` không chứa `promote`, `ApprovalToken` hay `StrategyRegistry` trong source — kiểm bằng test parse source.

Thăng hạng thật vẫn phải qua `StrategyRegistry.promote(key, ApprovalToken(...))`. Xem [strategy_registry.md](strategy_registry.md).
