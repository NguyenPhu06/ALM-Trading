# Ablation Study — Phase 15

Câu hỏi không phải "model đầy đủ chạy có tốt không" mà là "**mỗi thành phần có xứng đáng có mặt không**".

## Chín arm

```
BASELINE
BASELINE + LIQUIDITY
BASELINE + MARKET_STRUCTURE
BASELINE + ICHIMOKU
BASELINE + RSI
BASELINE + ADX
BASELINE + ATR
BASELINE + NN
FULL_MODEL
```

Mỗi arm là BASELINE cộng **đúng một** thành phần, đo out-of-sample trên cùng tập observation nền. Đó là điều làm cho đóng góp gia tăng đọc được: nếu ba indicator được thêm cùng lúc, không cách nào biết cái nào có tác dụng.

## Bốn verdict

| Verdict | Nghĩa |
| --- | --- |
| `IMPROVES` | tốt hơn BASELINE **và** khác biệt có ý nghĩa thống kê |
| `NOT_PROVEN` | tốt hơn trên giấy, không tách được khỏi nhiễu |
| `NO_IMPROVEMENT` | không tốt hơn |
| `HARMFUL` | kém hơn, và kém một cách có ý nghĩa |
| `INSUFFICIENT_DATA` | không đủ mẫu để phán |

Mặc định là **không cải thiện**. Một delta dương nhưng không có ý nghĩa thống kê được báo là `NOT_PROVEN` — không phải "cải thiện nhẹ". Một thành phần làm xấu đi được báo là `HARMFUL`, không bị lặng lẽ bỏ đi.

## "Thêm indicator không mặc nhiên tốt hơn"

`AblationReport.as_dict()["note"]` in nguyên văn:

> More components is not assumed better. Each arm must beat BASELINE out-of-sample to be reported as IMPROVES.

Và `best_arm` chỉ chọn trong các arm **reliable** — một arm 4 mẫu với expectancy khổng lồ không bao giờ thắng.

## Giá trị từng thành phần (section 14)

`component_value()` báo cáo cho mỗi trong bảy thành phần (liquidity, market structure, ichimoku, rsi, adx, atr, nn):

`delta_expectancy`, `delta_win_rate`, `delta_drawdown`, `effect_size`, `effect_band`, `sample_size`, verdict.

Kèm `ranking`, `most_valuable`, `proven`, `unproven`, `harmful` — và một disclaimer: đóng góp gia tăng **không** chứng minh thành phần đó *gây ra* thay đổi.

Một arm không được chạy được báo `ARM_NOT_RUN`, không bị bỏ qua im lặng.

Xem thêm: [ai_research_lab.md](ai_research_lab.md), [statistical_significance.md](statistical_significance.md), [ai_explainability.md](ai_explainability.md).
