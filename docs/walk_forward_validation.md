# Walk-Forward Validation — Phase 13

## Split theo thời gian, không bao giờ ngẫu nhiên

`ai/dataset/split.py` chia dataset theo thứ tự thời gian (mặc định 70/15/15). Module này còn export `random_split()` — hàm đó **luôn** raise `RandomSplitRefused`. Nó tồn tại để mọi nỗ lực shuffle time series đều gặp lỗi rõ ràng thay vì im lặng làm sai.

Không timestamp nào của TEST nằm trước timestamp cuối của TRAIN.

## Walk-forward

Cửa sổ walk-forward mở rộng dần: mỗi cửa sổ train trên toàn bộ lịch sử tới thời điểm cắt, rồi đo trên đoạn kế tiếp chưa từng thấy.

`WalkForwardWindow` mang **timestamp**, không phải chỉ số mảng — nên việc chọn dòng phải lọc theo thời gian (`train_start <= row.timestamp < train_end`), không được cắt lát `rows[a:b]`.

## Stability

Điểm ổn định là tỉ lệ giữa hiệu năng thấp nhất và cao nhất qua các cửa sổ. Một model tốt ở một giai đoạn nhưng sập ở giai đoạn khác sẽ có stability thấp và **không** đủ điều kiện làm challenger, dù metric tổng có đẹp.

## Baseline

Model phải so với **8 baseline** trong `ai/models/rule_baselines.py`: random, majority, momentum, regime, RSI, Ichimoku, ADX và combined rules. Không giả định neural network tốt hơn. Hoà với baseline vẫn tính là **không** vượt baseline.

## Kết luận về "edge"

`SignificanceEvaluator` trả ba verdict:

- `EDGE_DETECTED` — vượt mọi baseline **và** khoảng tin cậy bootstrap không chứa mức ngẫu nhiên **và** ổn định qua các giai đoạn;
- `NO_EDGE` — thiếu một trong các điều kiện trên, lý do ghi rõ (ví dụ `DOES_NOT_BEAT_BASELINES`);
- `INSUFFICIENT_DATA` — mẫu quá nhỏ để kết luận.

`INSUFFICIENT_DATA` là kết quả **đúng**, không phải lỗi. Với 60 dòng test, hệ thống nói "chưa đủ dữ liệu" thay vì tuyên bố có lợi thế.

Xem thêm: [walk_forward.md](walk_forward.md) (nền tảng Phase 4), [model_evaluation.md](model_evaluation.md).
