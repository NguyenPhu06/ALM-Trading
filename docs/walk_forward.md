# Validation theo thời gian và walk-forward

Phase 4 không bao giờ shuffle ngẫu nhiên sample time-series.

Split bất biến mặc định là 70% TRAIN, 15% VALIDATION và 15% TEST. Metadata lưu timestamp bắt đầu/kết thúc của từng phần. Scaler chỉ fit trên TRAIN trước khi transform validation hoặc test.

`ExpandingWalkForward` cung cấp interface nghiên cứu tiếp theo:

```text
Window 1: TRAIN[0:a] -> VALIDATE[a+1:b] -> TEST[b+1:c]
Window 2: TRAIN[0:a+n] -> VALIDATE[...] -> TEST[...]
```

Điểm bắt đầu train giữ cố định trong khi điểm kết thúc train mở rộng theo step đã cấu hình. Validation và test luôn đi sau train theo thời gian và không overlap. Phase 4 không tune hyperparameter hay chọn Neural Network; các thao tác đó thuộc phase sau và phải giữ tính cô lập của từng window.
