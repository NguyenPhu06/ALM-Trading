# Giới hạn dữ liệu tổ chức

Khi không có nguồn trực tiếp, `InstitutionalPositionProvider` trả `UNAVAILABLE`, proxy bằng `null` và confidence bằng 0. Hệ thống không tạo order book, bank-flow hay whale activity giả.

Nếu sau này có proxy từ volume, COT, liquidity behavior hoặc market structure, record bắt buộc gắn `is_proxy=true`, source, timestamp và confidence. Proxy là giả thuyết từ dữ liệu thị trường, không phải thông tin nội bộ tổ chức.

