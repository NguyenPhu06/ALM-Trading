# Thiên hướng, hợp lưu và NO_TRADE

Thiên hướng ưu tiên cấu trúc và tuân theo phân cấp khung thời gian. Trọng số chuẩn hóa mặc định là D1 0,35; H4 0,25; H1 0,20; M15 0,10; M5 0,06 và M1 0,04. Trong mỗi khung thời gian, xu hướng đã xác nhận đóng góp 80% trọng số và BOS/CHoCH gần nhất đóng góp tối đa 20%. Điểm có trọng số được ánh xạ thành tăng mạnh, tăng, trung lập, giảm hoặc giảm mạnh. Vì vậy, khung thời gian thấp không thể tùy ý ghi đè cấu trúc D1/H4/H1 đang đồng thuận.

`ConfluenceScore` được giới hạn từ 0 đến 10 để giải thích và xếp hạng; đây không phải xác suất. Các thành phần gồm độ lớn cấu trúc phân cấp và xác nhận xu hướng theo quy tắc xác định. Danh sách lý do ghi nhận cấu trúc đồng thuận, BOS, sweep và ngữ cảnh ADX; danh sách xung đột ghi nhận các trạng thái khung thời gian đối lập với thiên hướng phân cấp.

Đầu ra trở thành `NO_TRADE` khi có bất kỳ điều kiện an toàn nào được cấu hình, gồm thiếu dữ liệu khung thời gian, cấu trúc D1/H4 xung đột, biến động cực đoan, cấu trúc không rõ, thiếu ngữ cảnh thanh khoản, phiên không phù hợp, spread thực bất thường hoặc thiếu xác nhận cấu trúc/price action. Nếu không, trạng thái là `OBSERVE`, không bao giờ là `BUY` hay `SELL`.
