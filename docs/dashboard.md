# ALM Trading Command Center

Dashboard Phase 9 là frontend React/TypeScript/Vite tách khỏi FastAPI. Nó chỉ poll các endpoint `/dashboard/*` và render dữ liệu backend; không tính lại indicator, score, strategy hay risk.

Layout gồm system header, symbol switcher, market overview, MTF D1→M5, liquidity, indicators/SMC, neural probabilities, strategy explanation, risk, paper positions/DCA, equity/performance, journal, timeline và alert center. Dark theme dùng màu theo trạng thái NORMAL/WARNING/CRITICAL/BLOCKED và có breakpoint desktop/tablet/mobile.

Khi API lỗi hoặc payload stale, UI hiển thị `DATA UNAVAILABLE`/`STALE DATA`; dữ liệu cũ không được trình bày như dữ liệu mới. Environment luôn là PAPER và dashboard không có order control.
