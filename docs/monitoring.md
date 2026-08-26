# Monitoring và freshness

Overview theo dõi database, market data, AI model, strategy, paper engine và API với ONLINE/DEGRADED/OFFLINE. Mỗi response có timestamp, source, version, data_quality, last_update, data_age và stale state.

Frontend polling mỗi 10 giây. Kiến trúc API client được tách riêng để có thể thay polling bằng WebSocket về sau mà không đưa logic strategy vào UI.

Provider thiếu dữ liệu thật, model unavailable hoặc quality invalid phải hiển thị DEGRADED/OFFLINE và chặn new trade ở backend.
