# Đánh giá model

Dataset được giữ nguyên thứ tự `TRAIN → VALIDATION → TEST`. Model fit trên TRAIN, early stopping theo validation loss và chỉ đánh giá TEST sau khi training kết thúc. Test set không được dùng để chọn hyperparameter.

Classification report gồm accuracy, balanced accuracy, precision, recall, F1 và confusion matrix cho từng lớp UP/DOWN/NEUTRAL. ROC-AUC one-vs-rest chỉ được ghi khi lớp dương và âm đều tồn tại; ROC-AUC không phải metric duy nhất.

Calibration report chia xác suất của từng lớp thành bin và so sánh mean predicted probability với observed frequency. Confidence luôn bị đánh dấu `MODEL_CONFIDENCE_IS_UNCALIBRATED` cho đến khi báo cáo calibration chứng minh đủ chất lượng.

Lớp trading-relevant evaluation ghi prediction hit rate, conditional future return, MFE và MAE theo lớp dự đoán. Các số này là liên hệ nghiên cứu, có disclaimer `RESEARCH_ASSOCIATION_NOT_STRATEGY_PROFITABILITY`; chúng không phải profitability của strategy.

Training history lưu train/validation loss và accuracy theo epoch. Khi chênh lệch loss hoặc accuracy vượt ngưỡng cấu hình, trạng thái là `POSSIBLE_OVERFITTING`. Early stopping khôi phục trọng số tại validation loss tốt nhất.
