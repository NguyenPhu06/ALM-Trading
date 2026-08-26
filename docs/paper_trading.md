# Paper trading Phase 8

Paper service quản lý account, equity, positions, order, DCA, exit và journal trong môi trường `PAPER`. Entry chỉ được phép khi setup là `EXECUTABLE_SIMULATION`, risk cho phép, quality `VALID`, provider online và prediction hợp lệ.

Các control endpoint start/pause/stop/close-position chỉ tác động tới mô phỏng. Không có broker transport, trading credential hay `/live/order`. `LIVE_TRADING_ENABLED=false` và `PAPER_TRADING_ENABLED=true` là invariant bắt buộc.
