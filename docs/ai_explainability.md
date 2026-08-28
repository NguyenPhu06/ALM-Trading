# AI Explainability

`ai/evaluation/explainability.py` dùng **permutation importance** trên dữ liệu held-out: xáo trộn một nhóm feature, đo mức hiệu năng tụt.

## Cảnh báo bắt buộc

Module export hằng `DISCLAIMER`, và dashboard in nguyên văn:

> Permutation importance đo **liên hệ** trên dữ liệu held-out. Nó **không** chứng minh quan hệ nhân quả.

Feature quan trọng theo permutation không có nghĩa feature đó gây ra chuyển động giá. Hai feature tương quan có thể chia nhau importance một cách tuỳ tiện.

## Báo cáo theo nhóm, không theo cột

Importance được gộp theo `FEATURE_GROUPS` (market structure, liquidity, indicators, regime, session, MTF alignment, volatility, momentum). Với 141 feature, xếp hạng từng cột riêng lẻ vừa nhiễu vừa khó đọc; nhóm thì ổn định hơn và khớp với cách Strategy Engine suy nghĩ.

## Phân rã theo segment

`SegmentedEvaluator` báo cáo hiệu năng theo regime, theo session và theo timeframe. Một model tốt tổng thể nhưng thua ngẫu nhiên trong regime `RANGING` là một model ta cần biết rõ — chứ không phải một model tốt.

## Calibration

Ngoài accuracy, hệ thống đo Brier score, log loss và expected calibration error. Xác suất 0.8 phải đúng khoảng 80% số lần. Model tự tin sai nguy hiểm hơn model kém nhưng thành thật.

Xem thêm: [strategy_explainability.md](strategy_explainability.md), [model_evaluation.md](model_evaluation.md).
