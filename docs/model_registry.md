# Model Registry

`ImmutableModelRegistry` lưu mỗi model trong thư mục riêng theo `model_version`. Registry không ghi đè version cũ. Mỗi entry gồm:

- `model.npz`: trọng số và bias NumPy đã nén;
- `metadata.json`: dataset/feature version, training/validation/test period, hyperparameter, metric, scaler và training timestamp;
- `MODEL_CARD.md`: mục đích, dataset, feature, periods, giới hạn và failure mode đã biết.

`save_model()` từ chối path đã tồn tại. `load_model()` khôi phục đúng architecture/config; test bắt buộc prediction trước và sau serialization giống hệt nhau.

Experiment tracking bắt đầu bằng một file JSON bất biến cho mỗi run trong `data/experiments/`. Bản ghi chứa experiment ID, model/dataset/feature version, danh sách feature, hyperparameter, metrics và timestamp. `data/models/` cùng `data/experiments/` bị Git ignore.
