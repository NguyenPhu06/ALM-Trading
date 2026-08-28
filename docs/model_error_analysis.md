# Model Error Analysis — Phase 14

Khi một dự đoán sai, **sai như thế nào** mới là phần dùng được. Accuracy không phân biệt được model sai lúc không chắc chắn với model sai lúc rất chắc chắn — mà hai thứ đó khác nhau hoàn toàn.

## Mười một lớp lỗi

Mỗi dự đoán sai nhận **một lớp chính** cộng các **tag đóng góp**.

Lớp chính, theo hướng:

| Lớp | Khi nào |
| --- | --- |
| `FALSE_BULL` | dự đoán tăng, thị trường không tăng |
| `FALSE_BEAR` | dự đoán giảm, thị trường không giảm |
| `FALSE_NEUTRAL` | dự đoán đứng yên, thị trường chạy |

Tag theo mức tự tin (luôn có đúng một trong hai):

| Tag | Khi nào |
| --- | --- |
| `HIGH_CONFIDENCE_FAILURE` | confidence ≥ ngưỡng cấu hình |
| `LOW_CONFIDENCE_FAILURE` | dưới ngưỡng, hoặc không có confidence |

Tag theo bối cảnh, phát khi thành phần đó **mâu thuẫn** với dự đoán:

`REGIME_FAILURE`, `SESSION_FAILURE`, `STRUCTURE_FAILURE`, `INDICATOR_FAILURE`, `LIQUIDITY_FAILURE`.

`UNKNOWN` dành cho trường hợp không đọc được hướng nào.

## Tag là bất đồng, không phải nguyên nhân

Một tag nói: "thành phần này chỉ hướng ngược với dự đoán". Nó **không** nói thành phần đó gây ra lỗi. Tag được suy ra từ chính những gì observation đã ghi lại tại thời điểm T, nên nó là một quan sát về bất đồng, không phải một tuyên bố nhân quả.

## High confidence failure (section 16)

```
confidence = 0.82
prediction = BULL
actual     = BEAR
=> HIGH_CONFIDENCE_FAILURE = true
```

Ngưỡng nằm ở `phase_14.high_confidence_threshold` (mặc định 0.75), không hard-code. Confidence **đúng bằng** ngưỡng vẫn tính.

Đây là nhóm cần chú ý đặc biệt: model sai lúc tự tin nguy hiểm hơn model kém nhưng thành thật. `ErrorAnalyzer.summarize()` báo `high_confidence_failures`, `high_confidence_failure_rate`, và danh sách 10 trường hợp tự tin nhất (`worst`). Mỗi trường hợp cũng phát alert `HIGH_CONFIDENCE_FAILURE`.

## Tổng hợp

`summarize()` trả về: số mẫu, số đúng/sai, accuracy, đếm theo lớp, đếm theo regime, đếm theo session, và nhóm high-confidence. Bản ghi được lưu ở bảng `model_errors` với cột `high_confidence_failure` có index, nên truy vấn nhóm này là chuyện một dòng SQL.

Xem thêm: [forward_learning.md](forward_learning.md), [ai_explainability.md](ai_explainability.md), [monitoring.md](monitoring.md).
