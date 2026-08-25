# Neural Network Research Engine

Phase 5 cung cấp một mạng MLP ba lớp đầu ra được viết bằng NumPy cho nghiên cứu xác suất `UP`, `DOWN` và `NEUTRAL`. Tổng ba xác suất luôn bằng 1. Model không tạo `BUY`, `SELL`, position hay order.

Đầu vào là 58 feature MTF có version từ dataset Phase 4. `ModelInput` chỉ chứa timestamp, symbol, feature values/names, feature version và dataset version; constructor từ chối tên trường label, future return, MFE hoặc MAE.

Architecture dùng số hidden layer, hidden unit, dropout, learning rate, batch size, epoch, early stopping và random seed trong `config/settings.yaml`. Batch TRAIN được xử lý theo thứ tự, không shuffle giữa các giai đoạn. Mean/std đã được fit trên TRAIN ở Phase 4 và cùng scaler bất biến được dùng khi inference.

Training luôn so sánh với ba baseline: majority class, softmax logistic regression và decision stump. Không giả định Neural Network tốt hơn. Nếu balanced accuracy của model không vượt baseline tốt nhất, báo cáo phải ghi `NEURAL NETWORK DOES NOT BEAT BASELINE`.

Hiện database production chưa có dataset Phase 4 đạt readiness, vì vậy `scripts/train_model.py` từ chối training thay vì dùng dữ liệu sample hoặc fixture.
