# Strategy Intelligence Engine — Phase 6

Engine kết hợp trạng thái D1, H4, H1, M30, M15 và M5. Higher-timeframe bias dùng trend, structure, BOS và CHoCH; không có indicator hay neural network nào tự tạo lệnh. Khi HTF và LTF ngược nhau, kết quả là `TIMEFRAME_CONFLICT` và `WAIT_FOR_ALIGNMENT`.

Luồng xử lý chỉ dành cho nghiên cứu: market snapshot đã đóng → MTF → structure/liquidity/indicator → xác suất NN → score → risk gate → setup mô phỏng. Không có `LIVE_EXECUTION`, kết nối broker hay phương thức đặt lệnh.

Scoring dùng vector thành phần và trọng số trong cấu hình. Kết quả lưu từng component, phần đóng góp có trọng số, lý do và xung đột để có thể audit.

