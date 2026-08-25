# Trade Setup

`TradeSetup` lưu hướng, giá tham chiếu, regime, alignment, liquidity, structure, indicators, xác suất NN, risk, score, confidence và version. Trạng thái hợp lệ chỉ gồm `INVALID`, `WATCH`, `READY`, `EXECUTABLE_SIMULATION`.

`EXECUTABLE_SIMULATION` chỉ có nghĩa đủ điều kiện đưa vào mô phỏng. Risk phải cho phép, MTF không xung đột và score đạt ngưỡng. NN chỉ cung cấp `prob_up`, `prob_down`, `prob_neutral`, `confidence`; confidence cuối là tổng hợp nhiều nhóm feature.

Các khái niệm SMC/ICT là feature hình thành từ dữ liệu thị trường, không chứng minh lệnh nội bộ hay hành vi chắc chắn của tổ chức.

