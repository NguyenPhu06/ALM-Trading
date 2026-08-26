# Monitoring và freshness

Overview theo dõi database, market data, AI model, strategy, paper engine, orchestration và API với ONLINE/DEGRADED/OFFLINE/DISABLED. AI model là ONLINE khi đã có prediction thật; strategy là ONLINE khi đã có decision thật.

Mỗi response có `timestamp` (thời điểm trả lời), `source`, `version`, `data_quality`, `last_update`, `data_age_seconds`, `stale` và `max_age_seconds`.

Freshness được tính thật: `data_age_seconds = timestamp - last_update`, trong đó `last_update` là timestamp NGUỒN (nến, snapshot hoặc bản ghi), không phải thời điểm response. Payload cũ hơn `phase_9.dashboard_max_age_seconds` (mặc định 300s) là `stale` kể cả khi `data_quality` là VALID.

Payload không có timestamp nguồn có age không xác định và luôn được báo `stale`: freshness không xác định không bao giờ được trình bày như dữ liệu mới. Timestamp tương lai được kẹp về age 0 thay vì báo age âm.

Collection paper rỗng (positions, journal, performance) trả `data_quality: UNAVAILABLE` thay vì VALID — không có dữ liệu không phải là dữ liệu hợp lệ.

Frontend polling mỗi 10 giây và hiển thị cả tuổi dữ liệu. Kiến trúc API client tách riêng để có thể thay polling bằng WebSocket về sau mà không đưa logic strategy vào UI.

Provider thiếu dữ liệu thật, model unavailable hoặc quality invalid phải hiển thị DEGRADED/OFFLINE và chặn new trade ở backend.
