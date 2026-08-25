# Kế hoạch chuẩn bị Neural Network

Phase 3 và Phase 4 không train hoặc thực thi Neural Network. Package `ai/` chỉ chứa ranh giới dataset, feature, label, model, training và evaluation.

Feature được tính nghiêm ngặt tại T. Label offline có thể xem số candle đã đóng tiếp theo theo cấu hình và chứa future return, maximum favorable/adverse excursion, future drawdown và future volatility. Label được neo vào feature timestamp và lưu future end timestamp riêng. Giá trị tương lai không bao giờ đi vào `FeatureVector`.

Trước khi train, dự án vẫn cần dữ liệu thật đủ sâu cho mọi timeframe bắt buộc, kiểm toán chất lượng provider/lịch nghỉ, walk-forward split, leakage check, phân tích độ ổn định class/target, giả định transaction cost và đánh giá out-of-sample nghiêm ngặt. Đầu ra model phải nằm sau deterministic market intelligence và trước risk; model không bao giờ được bỏ qua risk hoặc gọi execution trực tiếp.
