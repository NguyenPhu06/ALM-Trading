# Time-based Exit

Thử nghiệm giờ chẵn dùng timezone cấu hình, không hard-code giờ địa phương. Tại checkpoint tiếp theo engine đánh giá lại structure, regime, risk, confidence, drawdown và thời gian giữ lệnh; output là `HOLD`, `REDUCE`, `EXIT` hoặc `INVALIDATE` cùng reason code.

Engine không mặc định thoát ở mọi checkpoint. Ngoài checkpoint có thể giữ đến lần đánh giá kế tiếp; structure bị phá hoặc risk vượt giới hạn được ưu tiên xử lý.

