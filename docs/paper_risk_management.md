# Quản trị rủi ro Paper Trading

Risk gate kiểm tra drawdown, exposure, position size, DCA count, daily loss, concurrent positions, volatility, spread, news, data quality, provider và model. Vi phạm tạo `ORDER_REJECTED` cùng `WHY_REJECTED`.

Daily Risk Manager lấy equity đầu ngày, tính PnL và drawdown theo ngày. Khi chạm giới hạn, entry mới bị pause; quản lý/thoát vị thế an toàn vẫn được phép. Global Kill Switch có cùng nguyên tắc.

Drawdown tài khoản = `(peak_equity - current_equity) / peak_equity`. Equity curve lưu timestamp, equity và drawdown.

