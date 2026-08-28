# Statistical Edge — Phase 14

`ai/edge/edge_detector.py` trả lời đúng một câu hỏi, và từ chối trả lời qua loa: **có bằng chứng nào cho thấy hệ thống này có lợi thế không?**

## Bốn verdict

| Verdict | Ý nghĩa |
| --- | --- |
| `EDGE_DETECTED` | expectancy dương, vượt **mọi** baseline, khoảng tin cậy không chứa 0, ổn định qua các giai đoạn / regime / session / timeframe |
| `UNSTABLE_EDGE` | dương tổng thể nhưng đến từ một phần — một phát hiện thật, và **không** phải thứ để giao dịch |
| `NO_EDGE` | trượt expectancy, ý nghĩa thống kê, hoặc một baseline |
| `INSUFFICIENT_DATA` | quá ít mẫu để nói bất cứ điều gì |

`report.edge` chỉ đúng với `EDGE_DETECTED`. `UNSTABLE_EDGE` **không phải** một edge.

## Chín baseline

Model phải vượt **tất cả**: `random`, `majority`, `buy_and_hold`, `momentum`, `rsi`, `ichimoku`, `adx`, `regime` — cộng champion hiện tại nếu có.

Baseline nào **thiếu** cũng chặn tuyên bố edge (`<tên>:MISSING`). Không có champion thì không chặn — không có gì để vượt.

**PnL dương một mình không bao giờ là edge.** `test_positive_pnl_alone_is_not_an_edge` truyền một chuỗi có lãi nhưng không kèm baseline nào và khẳng định verdict là `NO_EDGE`.

## Chỉ số

Sample size, expectancy, win rate, profit factor, net PnL, max drawdown, khoảng tin cậy bootstrap, độ ổn định theo giai đoạn, và độ nhất quán walk-forward. Tất cả tính trên **net** (`net_hypothetical_pnl`), không bao giờ gross.

Nhất quán được đo riêng theo ba chiều — regime, session, timeframe. Một segment dưới ngưỡng mẫu (`minimum_segment_samples`) không được tính là dương cũng không được tính là âm: nó đơn giản là chưa đủ dữ liệu để phán.

## Bằng chứng phải là forward (section 24)

`EdgeDetector.evaluate()` gọi `require_forward()` trước khi làm bất cứ điều gì. Truyền `BACKTEST` hay `PAPER` vào sẽ raise `EvidenceRefused` kèm tên nguồn bị từ chối.

Thứ tự sức mạnh bằng chứng:

```
BACKTEST < PAPER < FORWARD_OBSERVATION < DEMO_EXECUTION < LIVE_EXECUTION
```

`FORWARD_OBSERVATION` là nguồn đánh giá chính. `DEMO_EXECUTION` và `LIVE_EXECUTION` có tên trong từ vựng để một phase tương lai có chữ mà gọi — **không** code path nào trong repo này sinh ra chúng, và một test quét toàn bộ cây thư mục để giữ điều đó đúng.

Xem thêm: [walk_forward_validation.md](walk_forward_validation.md), [forward_learning.md](forward_learning.md), [champion_challenger.md](champion_challenger.md).
