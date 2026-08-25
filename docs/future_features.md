# Tương thích feature tương lai và Neural Network

Phase 1A không train model và không tạo giá trị feature ngẫu nhiên hoặc tổng hợp.

Các nhóm feature dự kiến:

- PRICE: return, range và ngữ cảnh candle từ `market_candles`.
- LIQUIDITY: sự kiện thanh khoản có timestamp do hệ thống suy ra.
- STRUCTURE: trạng thái HH/HL/LH/LL/BOS/CHoCH đã biết tại thời điểm quan sát.
- ICHIMOKU, RSI, ADX, ATR: giá trị do Indicator Engine ghi.
- TIME: feature UTC/lịch/session được suy ra mà không dùng dữ liệu tương lai.
- COT: vị thế tổ chức định kỳ, chỉ join sau thời điểm công bố khả dụng.
- INSTITUTIONAL PRESSURE: ước lượng có thể `NULL`, kèm confidence và metadata nguồn.

Pipeline tương lai: database → feature extraction → feature dataset → labeling → train → validation → test → walk-forward evaluation → model prediction. Dataset Builder phải dùng point-in-time join, ghi thời điểm dữ liệu thực sự khả dụng thay vì chỉ ngày báo cáo, giữ validation/test tách biệt theo thời gian và ngăn look-ahead leakage. `strategy_signals` và `trading_outcomes` cung cấp interface lưu signal/label tương lai; cả hai đều không kích hoạt execution.
