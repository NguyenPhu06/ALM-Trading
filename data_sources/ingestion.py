from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from data_quality import detect_market_data_gaps, validate_candle_batch
from data_quality.validator import timeframe_delta
from data_sources.providers.base import BaseMarketDataProvider
from database.models import MarketDataIngestion
from database.repositories import CandleRepository


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionReport:
    provider: str
    symbol: str
    timeframe: str
    request_start: datetime
    request_end: datetime
    rows_received: int
    rows_inserted: int
    rows_updated: int
    rows_skipped: int
    duplicates: int
    invalid_rows: int
    gaps: int
    duration_seconds: float
    status: str


class MarketDataIngestionService:
    def __init__(self, session: Session, provider: BaseMarketDataProvider):
        self.session = session
        self.provider = provider

    def import_historical(
        self, symbol: str, timeframe: str, start: datetime, end: datetime,
    ) -> IngestionReport:
        request_started = datetime.now(timezone.utc)
        monotonic_started = time.monotonic()
        rows = []
        try:
            rows = self.provider.fetch_historical(symbol, timeframe, start, end)
            validate_candle_batch(rows)
            gaps = detect_market_data_gaps(rows)
            upsert = CandleRepository(self.session).upsert_many(rows)
            duration = round(time.monotonic() - monotonic_started, 4)
            status = "SUCCESS_WITH_GAPS" if any(gap.expected_candles for gap in gaps) else "SUCCESS"
            report = IngestionReport(
                self.provider.name, symbol.upper(), timeframe.upper(), start, end,
                len(rows), upsert.inserted, upsert.updated, upsert.skipped,
                upsert.duplicates_in_batch, 0, len(gaps), duration, status,
            )
            self._record(report, request_started, None)
            logger.info(
                "market data ingestion: provider=%s symbol=%s timeframe=%s request_start=%s request_end=%s rows_received=%d rows_inserted=%d rows_skipped=%d duplicates=%d invalid_rows=0 gaps=%d duration=%.4f",
                self.provider.name, symbol, timeframe, start, end, len(rows),
                upsert.inserted, upsert.skipped, upsert.duplicates_in_batch, len(gaps), duration,
            )
            return report
        except Exception as exc:
            self.session.rollback()
            duration = round(time.monotonic() - monotonic_started, 4)
            report = IngestionReport(
                self.provider.name, symbol.upper(), timeframe.upper(), start, end,
                len(rows), 0, 0, 0, 0, len(rows) if rows else 0, 0, duration, "FAILED",
            )
            self._record(report, request_started, type(exc).__name__)
            logger.error(
                "market data ingestion failed: provider=%s symbol=%s timeframe=%s request_start=%s request_end=%s rows_received=%d duration=%.4f error=%s",
                self.provider.name, symbol, timeframe, start, end, len(rows), duration, type(exc).__name__,
            )
            raise

    def update_incremental(
        self, symbol: str, timeframe: str, *, end: datetime | None = None,
    ) -> IngestionReport:
        end = end or datetime.now(timezone.utc)
        latest = CandleRepository(self.session).latest(symbol.upper(), timeframe.upper(), source=self.provider.name)
        if latest is None:
            raise ValueError("incremental update requires existing provider data; run historical import first")
        start = latest.timestamp if not latest.is_closed else latest.timestamp + timeframe_delta(timeframe.upper())
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        return self.import_historical(symbol, timeframe, start, end)

    def continuous_poll(self, symbol: str, timeframe: str, *, interval_seconds: float=60,
                        max_cycles: int | None=None, sleeper=time.sleep) -> list[IngestionReport]:
        """Polling có giới hạn cho service/worker; provider tự xử lý retry/rate limit."""
        reports=[];cycles=0
        while max_cycles is None or cycles<max_cycles:
            reports.append(self.update_incremental(symbol,timeframe));cycles+=1
            if max_cycles is None or cycles<max_cycles:sleeper(interval_seconds)
        return reports

    def _record(self, report: IngestionReport, request_started: datetime, error: str | None) -> None:
        self.session.add(MarketDataIngestion(
            provider=report.provider, symbol=report.symbol, timeframe=report.timeframe,
            status=report.status, request_start=request_started,
            request_end=datetime.now(timezone.utc), rows_received=report.rows_received,
            rows_inserted=report.rows_inserted, rows_updated=report.rows_updated,
            rows_skipped=report.rows_skipped, invalid_rows=report.invalid_rows,
            gaps=report.gaps, duration_seconds=report.duration_seconds, last_error=error,
        ))
        self.session.commit()
