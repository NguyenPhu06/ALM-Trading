# Dataset Pipeline — Phase 13

`ai/dataset/` biến observation đã lưu thành dataset có version, kiểm tra được.

## Version

Ba version độc lập, khai báo ở `ai/dataset/versioning.py`:

| Hằng số | Giá trị | Ý nghĩa |
| --- | --- | --- |
| `FEATURE_VERSION` | `features_v1` | tập feature và cách tính |
| `LABEL_VERSION` | `labels_v1` | horizon, cost model, quy tắc gán nhãn |
| `PREPROCESSING_VERSION` | `scaler_v1` | cách fit và áp dụng scaler |

`dataset_id()` là hash nội dung của (feature version, label version, preprocessing version, khoảng thời gian, số dòng). Đổi bất kỳ thành phần nào thì dataset id đổi theo, nên không thể lẫn hai dataset khác nhau. Model nào train trên dataset nào thì `ModelRecord` ghi lại đúng ba version đó; inference với feature version lệch bị từ chối (`feature version mismatch`).

`DatasetAudit` ghi lại nguồn gốc mỗi dataset: khoảng thời gian, số dòng mỗi partition, số nhãn bị từ chối và lý do.

## Feature

`FeatureExtractor` sinh **141 feature** chia theo `FEATURE_GROUPS` (market structure, liquidity, indicators, regime, session, multi-timeframe alignment, volatility, momentum). Nhóm này chính là đơn vị mà explainability báo cáo.

Feature chỉ mô tả những gì biết được tại thời điểm T. Không feature nào đọc giá sau T.

## Gán nhãn

`LabelingEngine` chỉ gán nhãn khi horizon đã thực sự trôi qua. Nếu `now < entry_time + horizon`, hoặc cửa sổ dữ liệu không chạm tới deadline, engine trả `LabelRefusal` thay vì đoán. Chi tiết ở [labeling.md](labeling.md).

## Kiểm tra chất lượng

`DatasetQualityChecker` chặn sáu lớp leakage (`LeakageCode`): future price lọt vào feature, label trộn vào feature, scaler fit trên toàn bộ dataset, shuffle time series, overlap giữa các partition, và nhãn tạo trước khi horizon kết thúc.

## Scaler

Mean/std **chỉ** fit trên phần TRAIN rồi áp dụng nguyên trạng cho VALIDATION và TEST. Feature hằng số có std cỡ `1e-18` chứ không đúng bằng 0, nên guard là

```python
MINIMUM_DEVIATION = 1e-12
```

chứ không phải `std or 1.0` — nếu không, nhiễu float chia cho `1e-18` sẽ nổ thành giá trị vô nghĩa.

Xem thêm: [labeling.md](labeling.md), [data_leakage.md](data_leakage.md), [walk_forward_validation.md](walk_forward_validation.md).
