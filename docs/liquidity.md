# Feature thanh khoản Phase 3

Mức thanh khoản là mốc giá có thể đo lường, không phải bằng chứng về lệnh của tổ chức. Engine công bố swing high/low đã xác nhận, equal high/low, cực trị ngày/tuần/tháng trước, cực trị đang chạy của session hiện tại, cực trị session trước và cụm liquidity pool.

Hai swing cùng phía đã xác nhận thuộc một pool khi mỗi chênh lệch giá liên tiếp không vượt `equal_level_tolerance_points × point_size`. Cụm high được gọi là buy-side liquidity; cụm low là sell-side liquidity. Độ mạnh pool là hàm xác định có giới hạn dựa trên khoảng cách, số lần chạm, tuổi, timeframe, tính bằng nhau, độ nổi bật swing và mức liên quan session.

Sweep phía high yêu cầu `high > level`, `close < level` và tỷ lệ từ chối của râu trên so với range candle lớn hơn ngưỡng cấu hình. Đây là từ chối giảm tại buy-side liquidity. Sweep phía low đối xứng yêu cầu `low < level`, `close > level` và râu dưới đủ mạnh. Mỗi sự kiện lưu penetration, rejection, rejection ratio, timestamp mức trở nên khả dụng, hướng, timeframe và strength.

Một wick đơn lẻ không phải sweep. Level chỉ hoạt động từ timestamp xác nhận nhân quả; việc fill hoặc rejection về sau không thể được ghi ngược vào snapshot trước đó.
