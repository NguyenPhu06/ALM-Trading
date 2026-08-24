from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from data_quality.validator import timeframe_delta
from data_sources.normalizer import CandleNormalizer, normalize_symbol, normalize_timeframe
from data_sources.providers.base import BaseMarketDataProvider, ProviderHealth, ProviderStatus


logger = logging.getLogger(__name__)


class ProviderRequestError(RuntimeError):
    pass


Transport = Callable[[str, float], dict[str, Any]]


class HistoricalFXProvider(BaseMarketDataProvider):
    """Twelve Data REST adapter for authorized historical/native FX OHLC."""

    name = "twelve_data"
    supported_symbols = ("EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD")
    supported_timeframes = ("M1", "M5", "M15", "H1", "H4", "D1")
    INTERVALS = {"M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h", "D1": "1day"}

    def __init__(
        self, *, api_key: str | None, base_url: str = "https://api.twelvedata.com",
        timeout: float = 30.0, rate_limit: float = 8.0, max_retries: int = 3,
        backoff_seconds: float = 1.0, transport: Transport | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limit = max(rate_limit, 0.0)
        self.max_retries = max(1, max_retries)
        self.backoff_seconds = max(backoff_seconds, 0.0)
        self.transport = transport or self._http_json
        self.sleeper = sleeper
        self.normalizer = CandleNormalizer()
        self.connected = False
        self.last_success: datetime | None = None
        self.last_error: str | None = None
        self.last_latency: float | None = None
        self._last_request_monotonic: float | None = None

    def connect(self) -> None:
        if not self.api_key:
            raise ProviderRequestError("MARKET_DATA_API_KEY is not configured")
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def fetch_historical(
        self, symbol: str, timeframe: str, start: datetime, end: datetime,
    ) -> list[dict[str, Any]]:
        symbol, timeframe, start, end = self._validate_request(symbol, timeframe, start, end)
        if not self.connected:
            self.connect()
        delta = timeframe_delta(timeframe)
        max_span = delta * 4999
        cursor = start
        rows: dict[datetime, dict[str, Any]] = {}
        while cursor <= end:
            chunk_end = min(end, cursor + max_span)
            for candle in self._fetch_chunk(symbol, timeframe, cursor, chunk_end):
                rows[candle["timestamp"]] = candle
            cursor = chunk_end + delta
        return [rows[timestamp] for timestamp in sorted(rows)]

    def fetch_latest(self, symbol: str, timeframe: str) -> dict[str, Any] | None:
        timeframe = normalize_timeframe(timeframe)
        now = datetime.now(timezone.utc)
        rows = self.fetch_historical(symbol, timeframe, now - timeframe_delta(timeframe) * 4, now)
        return rows[-1] if rows else None

    def fetch_incremental(
        self, symbol: str, timeframe: str, start: datetime, end: datetime | None = None,
    ) -> list[dict[str, Any]]:
        return self.fetch_historical(symbol, timeframe, start, end or datetime.now(timezone.utc))

    def health_check(self) -> ProviderStatus:
        if not self.api_key:
            status = ProviderHealth.UNCONFIGURED
        elif self.last_error and self.last_success is None:
            status = ProviderHealth.ERROR
        elif self.last_error:
            status = ProviderHealth.DEGRADED
        else:
            status = ProviderHealth.HEALTHY
        return ProviderStatus(
            self.name, status, self.last_success, self.last_error, self.last_latency,
            self.supported_symbols, self.supported_timeframes,
        )

    def _fetch_chunk(
        self, symbol: str, timeframe: str, start: datetime, end: datetime,
    ) -> list[dict[str, Any]]:
        params = {
            "symbol": f"{symbol[:3]}/{symbol[3:]}",
            "interval": self.INTERVALS[timeframe],
            "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
            "end_date": end.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": "UTC", "order": "asc", "outputsize": "5000",
            "format": "JSON", "apikey": self.api_key or "",
        }
        safe_context = {"provider": self.name, "symbol": symbol, "timeframe": timeframe, "request_start": start, "request_end": end}
        started = time.monotonic()
        for attempt in range(self.max_retries):
            self._wait_for_rate_limit()
            try:
                payload = self.transport(f"{self.base_url}/time_series?{urlencode(params)}", self.timeout)
                if payload.get("status") == "error":
                    raise ProviderRequestError(str(payload.get("message", "provider error")))
                values = payload.get("values") or []
                rows = [self._normalize_value(value, symbol, timeframe) for value in values]
                self.last_success = datetime.now(timezone.utc)
                self.last_error = None
                self.last_latency = round(time.monotonic() - started, 4)
                logger.info("market data provider success: %s rows_received=%d duration=%.4f", safe_context, len(rows), self.last_latency)
                return rows
            except (HTTPError, URLError, TimeoutError, ProviderRequestError, ValueError, KeyError) as exc:
                self.last_error = type(exc).__name__
                retryable = not isinstance(exc, ProviderRequestError) or "invalid" not in str(exc).lower()
                if attempt + 1 >= self.max_retries or not retryable:
                    self.last_latency = round(time.monotonic() - started, 4)
                    logger.error("market data provider failure: %s error=%s duration=%.4f", safe_context, type(exc).__name__, self.last_latency)
                    raise ProviderRequestError(f"{self.name} request failed: {type(exc).__name__}") from exc
                self.sleeper(self.backoff_seconds * (2 ** attempt))
        raise AssertionError("unreachable")

    def _normalize_value(self, value: dict[str, Any], symbol: str, timeframe: str) -> dict[str, Any]:
        raw_timestamp = value.get("timestamp") or value.get("datetime")
        if isinstance(raw_timestamp, str) and raw_timestamp.isdigit():
            raw_timestamp = int(raw_timestamp)
        if isinstance(raw_timestamp, str) and "+" not in raw_timestamp and not raw_timestamp.endswith("Z"):
            raw_timestamp = f"{raw_timestamp}+00:00"
        now = datetime.now(timezone.utc)
        raw = {
            **value, "timestamp": raw_timestamp, "symbol": symbol, "timeframe": timeframe,
            "is_closed": True, "provider": self.name, "provider_timestamp": raw_timestamp,
        }
        candle = self.normalizer.normalize(raw, source=self.name)
        candle["is_closed"] = candle["timestamp"] + timeframe_delta(timeframe) <= now
        return candle

    def _wait_for_rate_limit(self) -> None:
        if self.rate_limit <= 0 or self._last_request_monotonic is None:
            self._last_request_monotonic = time.monotonic()
            return
        minimum_interval = 60.0 / self.rate_limit
        elapsed = time.monotonic() - self._last_request_monotonic
        if elapsed < minimum_interval:
            self.sleeper(minimum_interval - elapsed)
        self._last_request_monotonic = time.monotonic()

    @staticmethod
    def _validate_request(symbol: str, timeframe: str, start: datetime, end: datetime) -> tuple[str, str, datetime, datetime]:
        symbol = normalize_symbol(symbol)
        timeframe = normalize_timeframe(timeframe)
        if symbol not in HistoricalFXProvider.supported_symbols:
            raise ValueError(f"unsupported FX symbol: {symbol}")
        if timeframe not in HistoricalFXProvider.supported_timeframes:
            raise ValueError(f"unsupported timeframe: {timeframe}")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("provider timestamps must be timezone-aware")
        start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
        if start > end:
            raise ValueError("start must not be after end")
        return symbol, timeframe, start, end

    @staticmethod
    def _http_json(url: str, timeout: float) -> dict[str, Any]:
        request = Request(url, headers={"User-Agent": "ALM-Trading/2.0", "Accept": "application/json"})
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
