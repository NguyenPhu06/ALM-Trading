# DCA mô phỏng

DCA Phase 6 có giới hạn `max_entries`, `entry_spacing`, `position_size`, `max_exposure` và `max_drawdown`. Mỗi lần thêm vị thế chỉ được phép khi regime còn hợp lệ, structure chưa invalidated, risk còn cho phép và chưa chạm giới hạn.

Structure invalidated tạo `NO_MORE_DCA_STRUCTURE_INVALIDATED`. DCA không được dùng để che giấu một chiến lược sai và không có đường dẫn gửi lệnh thật.

