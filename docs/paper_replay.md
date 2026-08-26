# Market Replay

Replay sắp candle theo timestamp và chỉ chuyển candle đã đóng cho handler. Tại bước T, handler chỉ nhận lịch sử trước T; candle tương lai không xuất hiện.

Replay dùng để debug entry, position update, DCA, exit, journal và equity. Nó không tối ưu strategy và không chứng minh profitability.

