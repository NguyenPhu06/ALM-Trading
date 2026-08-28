# Model Registry

`ImmutableModelRegistry` lưu mỗi model trong thư mục riêng theo `model_version`. Registry không ghi đè version cũ. Mỗi entry gồm:

- `model.npz`: trọng số và bias NumPy đã nén;
- `metadata.json`: dataset/feature version, training/validation/test period, hyperparameter, metric, scaler và training timestamp;
- `MODEL_CARD.md`: mục đích, dataset, feature, periods, giới hạn và failure mode đã biết.

`save_model()` từ chối path đã tồn tại. `load_model()` khôi phục đúng architecture/config; test bắt buộc prediction trước và sau serialization giống hệt nhau.

Experiment tracking bắt đầu bằng một file JSON bất biến cho mỗi run trong `data/experiments/`. Bản ghi chứa experiment ID, model/dataset/feature version, danh sách feature, hyperparameter, metrics và timestamp. `data/models/` cùng `data/experiments/` bị Git ignore.

## Phase 13 — registry vòng đời

`ImmutableModelRegistry` ở trên là kho artifact bất biến. Phase 13 bổ sung `ModelRegistry` (`ai/model_registry/registry.py`) trả lời một câu hỏi khác: **model nào đang là thẩm quyền** cho mỗi `ModelTask`.

Mỗi `ModelRecord` ghi: `model_id`, `model_version`, `feature_version`, `training_dataset_version`, `preprocessing_version`, `training_timestamp`, `validation_metrics`, `test_metrics`, `walk_forward_metrics`, `regime_metrics`, `session_metrics` và `state`.

Trạng thái đi theo `ALLOWED_TRANSITIONS`:

```
EXPERIMENTAL -> VALIDATED -> CANDIDATE -> CHAMPION -> RETIRED
             -> REJECTED
```

`promote()` bắt buộc có `ApprovalToken` (người duyệt + lý do) và raise `PromotionRefused` nếu `AI_AUTO_PROMOTE` bật — mà cờ đó không thể bật, vì validator ở `config/settings.py` chặn ngay lúc khởi động.

Artifact được `scrub_artifact()` làm sạch trước khi ghi: mọi key nhạy cảm bị xoá ở mọi độ sâu, nên không credential nào lọt vào file model. Artifact nằm ngoài Git; database chỉ giữ metadata và đường dẫn.

Xem thêm: [champion_challenger.md](champion_challenger.md), [model_drift.md](model_drift.md), [ai_learning.md](ai_learning.md).
