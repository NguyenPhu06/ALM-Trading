# Market-data providers

Interface chuẩn có latest quote, recent/historical candles, symbol info và market status. Adapter Twelve Data hiện có chỉ hoạt động khi người dùng cung cấp API key hợp lệ trong `.env`. Database gateway chỉ đọc dữ liệu thực đã chuẩn hóa và loại nguồn `local_csv` khỏi live snapshot.

Provider health dùng ONLINE, DEGRADED, OFFLINE, RATE_LIMITED và AUTH_ERROR. Retry, timeout, rate limit và logging nằm ở adapter/ingestion; log không chứa secret.

Mock provider chỉ nhận fixture xác định để test pipeline, không dùng đo profitability.

