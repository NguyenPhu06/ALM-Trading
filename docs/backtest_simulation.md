# Mô phỏng backtest và DCA

`SnapshotStrategy` chỉ nhận `MarketStateSnapshot` và trả về mô tả quyết định. Module này không có API broker. `DCASimulator` chỉ mở và thêm các điểm vào lệnh trong bộ nhớ, đồng thời tuân thủ các giới hạn rõ ràng về số lần vào, tổng mức phơi nhiễm, khoảng cách giá bất lợi và drawdown tối đa. Việc phân loại giao dịch ngược xu hướng được thực hiện bằng cách so sánh hướng mô phỏng với thiên hướng khung thời gian lớn đã lưu.

`TimeBasedExitEngine` đánh giá tại mốc thời gian kế tiếp theo lịch và trả về `HOLD`, `EXIT`, `REDUCE` hoặc `INVALIDATE` dựa trên thời gian nắm giữ, sự vô hiệu của HTF, drawdown và biến động cực đoan. Ngữ cảnh đánh giá lưu xu hướng, cấu trúc, RSI, ADX, Ichimoku, thanh khoản, biến động và PnL mô phỏng. Không có dữ liệu nào được gửi đến hệ thống thực thi lệnh.

Các mô phỏng đã đóng có thể được ghi vào `simulated_trades`. Đây là bảng kiểm toán mô phỏng, không phải bảng lệnh và không có khả năng đặt giao dịch.
