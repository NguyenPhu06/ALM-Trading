# Statistical Significance — Phase 15

Bốn thứ được báo cáo cho mọi so sánh, và một lợi thế chỉ được tuyên bố khi cả bốn đồng ý:

1. **sample size** — dưới ngưỡng thì verdict là `INSUFFICIENT_DATA`, không phải một kết luận yếu;
2. **confidence interval** — bootstrap, phải không chứa 0;
3. **effect size** — Cohen's d, phải không nằm ở mức không đáng kể;
4. **stability** — dấu phải nhất quán qua các giai đoạn.

## Vì sao có effect size

Một khác biệt **có ý nghĩa thống kê vẫn có thể vô nghĩa về kinh tế**. Với đủ mẫu, mọi thứ đều tách được. `minimum_effect` (mặc định 0.20) là hàng rào thứ hai: khác biệt nhỏ hơn thế bị gắn `EFFECT_BELOW_0.2` dù khoảng tin cậy có đẹp đến đâu.

`EFFECT_BANDS` dùng quy ước Cohen (0.20 / 0.50 / 0.80) chỉ để **gọi tên** độ lớn — không phải để chúc phúc cho nó.

## Trường hợp thoái hoá

Nếu không có độ lệch chuẩn gộp — thường là một arm có phương sai bằng 0 — thì không có độ lớn nào để phán. Kết quả bị gắn `EFFECT_SIZE_UNAVAILABLE` và **không** được gọi là significant.

Đây là một lỗi thật đã bị bắt trong lúc phát triển: bootstrap trên hai dãy hằng số cho khoảng tin cậy không chứa 0 và đọc ra như một kết quả dứt khoát. Dữ liệu thật không bao giờ có phương sai 0, nhưng một fixture thì có.

## Bốn verdict

| Verdict | Nghĩa |
| --- | --- |
| `SIGNIFICANT` | vượt cả bốn hàng rào |
| `NOT_SIGNIFICANT` | trượt khoảng tin cậy hoặc effect size |
| `UNSTABLE` | tách được khỏi 0 nhưng dấu đổi giữa các giai đoạn |
| `INSUFFICIENT_DATA` | quá ít mẫu để nói bất cứ điều gì |

## Không tuyên bố edge từ mẫu nhỏ

`SignificanceTester.absolute()` và `.compare()` đều kiểm sample size **trước tiên** và trả `INSUFFICIENT_DATA` mà không tính gì thêm. Ngưỡng nằm ở `phase_15.minimum_samples` (mặc định 100).

Xem thêm: [multiple_testing.md](multiple_testing.md), [statistical_edge.md](statistical_edge.md), [walk_forward_validation.md](walk_forward_validation.md).
