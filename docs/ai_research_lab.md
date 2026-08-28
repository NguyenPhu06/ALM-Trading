# AI Research Lab — Phase 15

Phase 15 là khung nghiên cứu để so sánh chiến lược, tổ hợp feature và model một cách khách quan, **chỉ trên dữ liệu forward observation**.

Nó trả lời mười câu hỏi:

| # | Câu hỏi | Module |
| --- | --- | --- |
| 1 | Chiến lược nào có lợi thế thống kê? | `research/experiments.py`, `research/significance.py` |
| 2 | Nó chạy được ở regime nào? | `research/matrices.py` |
| 3 | Ở session nào? | `research/matrices.py` |
| 4 | Timeframe nào tốt nhất? | `research/matrices.py` |
| 5 | NN có cải thiện chiến lược nền không? | `research/nn_value.py` |
| 6 | Liquidity + structure có hơn indicator không? | `research/ablation.py` |
| 7 | Thêm Ichimoku/RSI/ADX có tốt hơn không? | `research/ablation.py` |
| 8 | DCA cải thiện hay làm xấu risk-adjusted? | `research/dca.py` |
| 9 | Model nào đang là Champion? | `research/champion.py`, `research/registry.py` |
| 10 | Khi nào nên loại một model/chiến lược? | `rejection_criteria()` |

## Không có gì trong đây thực thi

Không module nào trong `research/` cầm execution client, import `execution.*` hay `paper.*`, hay ghi vào một setting. `tests/test_phase15_safety.py` parse **mọi** module trong package để chứng minh, và chạy toàn bộ study rồi so lại tám cờ an toàn.

## Mặc định là "không"

Đây là điểm thiết kế quan trọng nhất của lab. Mọi câu trả lời mặc định đều là phủ định:

- một component **không** cải thiện chiến lược → phải chứng minh ngược lại;
- NN **chưa được chứng minh có giá trị** (`NN_VALUE_NOT_PROVEN`);
- DCA **không** giúp → `recommended` mặc định là `NO_DCA`;
- **không có edge** cho tới khi vượt mọi baseline, đủ mẫu, và ổn định.

Một kết quả tốt hơn nhưng không tách được khỏi nhiễu được báo là `NOT_PROVEN`, không phải "cải thiện nhỏ".

## Đơn vị bằng chứng

`ResearchObservation` là một forward observation đã ghi, rút gọn về những gì nghiên cứu cần. `net_pnl` **luôn là net** sau spread, commission, slippage và swap — so sánh trên gross sẽ xếp hạng chiến lược theo mức độ giao dịch nhiều chứ không phải theo mức kiếm được.

`require_forward_only()` kiểm tra **từng dòng**: một dòng backtest lẫn vào tập forward bị từ chối theo tên, không bị trung bình hoá vào kết quả.

## Chạy

```bash
python -m scripts.run_research_lab --days 180
python -m scripts.run_research_lab --dry-run
```

Job này tách holdout, chạy mọi study trên phần research, mở holdout **một lần** ở cuối, rồi ghi JSON + Markdown vào `reports/research/`. Nó từ chối khởi động nếu bất kỳ cổng execution nào đang mở.

Xem thêm: [strategy_registry.md](strategy_registry.md), [ablation_study.md](ablation_study.md), [strategy_comparison.md](strategy_comparison.md), [statistical_significance.md](statistical_significance.md), [multiple_testing.md](multiple_testing.md), [champion_challenger.md](champion_challenger.md).
