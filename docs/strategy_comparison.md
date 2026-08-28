# Strategy Comparison — Phase 15

## Thí nghiệm là cấu hình, không phải code

`CATALOGUE` trong `research/experiments.py` khai báo tám thí nghiệm section 2 yêu cầu:

| Tên | Feature |
| --- | --- |
| `smc` | liquidity + market structure |
| `ichimoku` | ichimoku |
| `rsi` | rsi |
| `adx` | adx |
| `indicators` | ichimoku + rsi + adx |
| `smc_indicators` | liquidity + structure + indicators |
| `smc_nn` | liquidity + structure + NN |
| `smc_nn_indicators` | tất cả |

Thêm một biến thể là thêm một dòng cấu hình, không phải một nhánh code. Một feature family không tồn tại bị `UnknownFeatureFamily` từ chối ngay lúc khởi tạo.

## Định danh tái lập được

`ExperimentSpec.experiment_id` là hash nội dung của mười trường section 5 yêu cầu: strategy/feature/model/dataset/label version, ba khoảng thời gian, và cấu hình.

`timestamp` **cố ý bị loại khỏi hash**. Chạy lại đúng cấu hình đó trên đúng dữ liệu đó phải cho cùng một id — nếu không, sổ multiple testing sẽ đếm một giả thuyết thành hai.

## Chỉ số (section 7)

`sample_size`, `win_rate`, `loss_rate`, `expectancy`, `net_pnl`, `profit_factor`, `average_win`, `average_loss`, `average_mae`, `average_mfe`, `worst_mae`, `best_mfe`, `maximum_drawdown`, `return_over_drawdown`, `sharpe_like`, `sortino_like`, `prediction_accuracy`, `calibration`, `tail_loss`.

Hai quy ước:

- Tỉ số cần mẫu số trả `None` khi mẫu số không tồn tại. Một chiến lược không có lệnh thua **không có** profit factor; báo `inf` mời gọi một so sánh vô nghĩa.
- **Sharpe-*like*** và **Sortino-*like*** là cố ý. Chúng tính trên mỗi observation, **không annualise** — forward observation đến ở khoảng cách không đều, và một hệ số annualise sẽ là con số bịa ra.

## Ma trận (sections 8, 9, 10)

Cùng một cỗ máy, ba chiều: regime, session, timeframe. Mỗi ô báo `sample_size`, `win_rate`, `expectancy`, `net_pnl`, `maximum_drawdown`, `average_mae`, `average_mfe` và cờ `reliable`.

Ô dưới ngưỡng mẫu **vẫn được in** — giấu nó khiến một ma trận thưa trông như một ma trận đầy đủ — nhưng `best`, `profitable` và `losing` chỉ xét ô reliable.

Một model tốt trên M5 chưa nói gì về H1. Một chiến lược có lãi tổng thể vẫn có thể lỗ ở BEAR. Cả hai điều đó được khẳng định bằng test.

## Chuyển regime (section 18)

`transition_study()` đặt các observation *trong lúc regime đang đổi* cạnh trạng thái ổn định, đặt tên từng chuyển tiếp (`BULL->BEAR`, `RANGE->BULL`, …), và ghi rõ: một ô chuyển tiếp đếm observation có regime khác regime trước đó — **không phải** một khẳng định về nhân quả.

Xem thêm: [ai_research_lab.md](ai_research_lab.md), [statistical_significance.md](statistical_significance.md).
