# Rủi ro và ranh giới của model

Luồng kiến trúc bắt buộc:

```text
Market Intelligence
        ↓
Rule Engine
        ↓
Neural Network
        ↓
Risk Engine
```

Neural Network không được bỏ qua Rule Engine hoặc Risk Engine. `NeuralInferenceEngine` chỉ trả `ModelPrediction` và structured decision context; nó không có `place_order`, `open_position` hay `close_position`. `action` trong context Phase 5 luôn là `null`.

Risk Engine tương lai vẫn phải thực thi maximum exposure, drawdown limit, position sizing và mọi circuit breaker độc lập với confidence. Model confidence chưa calibration không được xem là xác suất thực. Thay đổi regime, class imbalance, dữ liệu thiếu/stale và distribution shift là failure mode đã biết.

Prediction kết hợp historical outcome chỉ là interface cho backtest phase sau. Không prediction nào được chuyển trực tiếp thành live order. `LIVE_TRADING_ENABLED` phải luôn là `false` trong Phase 5.
