# Paper trading Phase 7

`PaperExecutionProvider` chỉ mô phỏng trong bộ nhớ với submit/modify/close/get positions. `PaperOrder` lưu ID, symbol, direction, entry, size, stop, take profit, timestamp, strategy version và model version.

Không có broker transport, tài khoản giao dịch hay endpoint đặt lệnh. `LIVE_TRADING_ENABLED=false` là invariant bắt buộc.

