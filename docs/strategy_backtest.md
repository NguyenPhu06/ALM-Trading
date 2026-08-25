# Backtest chiến lược Phase 6

Backtest chạy theo thứ tự timestamp và chỉ nhận event/feature đã biết tại thời điểm đó. `source_timestamp > timestamp` bị từ chối. PnL báo cả gross, spread, commission, slippage và net.

Metrics gồm số trade, win/loss rate, profit factor, expectancy, average win/loss, maximum drawdown, Sharpe/Sortino khi đủ điều kiện, holding time, DCA depth/frequency và time-exit frequency. Có phân nhóm regime, session, D1 bias, H4 bias; walk-forward dùng các cửa sổ train/validation/test tách biệt.

Ablation không giả định thêm feature sẽ tốt hơn. Random control có seed cố định để tái lập. Hiện dữ liệu production chưa đủ để chứng minh edge, vì vậy trạng thái trung thực là **NO STATISTICAL EDGE DETECTED**.

