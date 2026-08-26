# Alert Engine

Alert types gồm liquidity sweep, BOS, CHoCH, MTF conflict, strategy ready/invalidated, DCA trigger/block, exit, risk warning/block, model/data/provider errors. Severity gồm LOW, MEDIUM, HIGH, CRITICAL.

Dashboard notification được triển khai nội bộ và alert history lưu PostgreSQL. Webhook/email/Telegram chỉ là interface unavailable; không hard-code credential. API hỗ trợ lọc symbol, type, severity và unread.
