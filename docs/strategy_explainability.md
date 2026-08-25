# Explainability và giới hạn

Mỗi setup có feature components, weighted components, conflicts và reason codes bắt đầu bằng `WHY_WATCH`, `WHY_READY` hoặc `WHY_INVALIDATED`. Exit dùng các mã như `EXIT_STRUCTURE_INVALIDATED`, `EXIT_REGIME_CHANGED`, `EXIT_TIME_LIMIT`; hold dùng `HOLD_TREND_REMAINS_VALID`.

Score và confidence không phải xác suất sinh lời. Liquidity sweep không đảm bảo reversal; market structure không đảm bảo dự báo; neural network không có quyền quyết định giao dịch. Model unavailable, data quality failure và extreme volatility đều có thể khiến risk gate chặn mô phỏng.

