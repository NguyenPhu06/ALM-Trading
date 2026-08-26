# Mô phỏng khớp lệnh

Execution engine ưu tiên bid/ask thật. Nếu quote không có bid/ask, engine dùng spread model cấu hình và ghi `spread_source=CONFIGURED_FALLBACK_MODEL`.

Execution price bao gồm fixed, percentage và volatility-based slippage. Commission hỗ trợ phí cố định và phần trăm notional. Kết quả luôn tách gross PnL, commission, slippage và net PnL; latency cũng được mô phỏng.

Engine chỉ nhận `TradingEnvironment.PAPER`. Mọi yêu cầu LIVE phát sinh `LIVE_EXECUTION_BLOCKED`.

