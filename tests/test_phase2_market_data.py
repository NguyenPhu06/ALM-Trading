from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.error import URLError

import pytest

from backtest import BacktestDataLoader
from data_quality import DataValidationError, calculate_freshness, detect_market_data_gaps
from data_sources.ingestion import MarketDataIngestionService
from data_sources.health import MarketDataHealthService
from data_sources.providers.base import BaseMarketDataProvider, ProviderHealth, ProviderStatus
from data_sources.providers.historical_fx import HistoricalFXProvider
from data_sources.resampler import MarketDataResampler
from database.models import MarketCandle, MarketDataIngestion
from database.repositories import CandleRepository
from features.regime.service import MarketRegimeService


UTC = timezone.utc


def candle(timestamp: datetime, timeframe: str = "M1", *, source: str = "test", price: str = "1.1"):
    value = Decimal(price)
    return {
        "timestamp": timestamp, "symbol": "EURUSD", "timeframe": timeframe,
        "open": value, "high": value + Decimal("0.01"),
        "low": value - Decimal("0.01"), "close": value + Decimal("0.001"),
        "volume": Decimal("10"), "tick_volume": Decimal("20"), "spread": Decimal("0.0001"),
        "is_closed": True, "source": source, "provider": source,
        "provider_timestamp": timestamp,
    }


def test_twelve_data_provider_normalizes_real_response_contract_and_hides_key(caplog):
    payload = {"values": [{
        "datetime": "2026-08-21 10:00:00", "open": "1.1000", "high": "1.1010",
        "low": "1.0990", "close": "1.1005", "volume": "42",
    }]}
    provider = HistoricalFXProvider(
        api_key="super-secret-key", transport=lambda _url, _timeout: payload,
        rate_limit=0, max_retries=1,
    )
    rows = provider.fetch_historical(
        "EUR/USD", "M15", datetime(2026, 8, 21, 10, tzinfo=UTC),
        datetime(2026, 8, 21, 10, tzinfo=UTC),
    )
    assert rows[0]["symbol"] == "EURUSD"
    assert rows[0]["timeframe"] == "M15"
    assert rows[0]["timestamp"].tzinfo == UTC
    assert rows[0]["source"] == "twelve_data"
    assert "super-secret-key" not in caplog.text


def test_provider_retry_is_finite_and_recovers():
    calls = []

    def transport(_url, _timeout):
        calls.append(1)
        if len(calls) == 1:
            raise URLError("temporary")
        return {"values": []}

    provider = HistoricalFXProvider(
        api_key="key", transport=transport, sleeper=lambda _seconds: None,
        rate_limit=0, max_retries=2, backoff_seconds=0,
    )
    assert provider.fetch_historical(
        "EURUSD", "M1", datetime(2026, 8, 21, tzinfo=UTC),
        datetime(2026, 8, 21, tzinfo=UTC),
    ) == []
    assert len(calls) == 2


def test_provider_health_unconfigured():
    status = HistoricalFXProvider(api_key=None).health_check()
    assert status.status is ProviderHealth.UNCONFIGURED


def test_provider_marks_proven_open_candle_unclosed():
    provider = HistoricalFXProvider(api_key="key")
    raw = {"datetime": "2999-01-01 00:00:00", "open": "1", "high": "1", "low": "1", "close": "1"}
    assert provider._normalize_value(raw, "EURUSD", "H1")["is_closed"] is False


def test_source_aware_upsert_is_idempotent_and_allows_two_sources(db_session):
    repository = CandleRepository(db_session)
    timestamp = datetime(2026, 8, 21, 10, tzinfo=UTC)
    first = candle(timestamp, source="provider-a")
    assert repository.upsert_many([first]).inserted == 1
    assert repository.upsert_many([first]).skipped == 1
    changed = {**first, "close": Decimal("1.105")}
    assert repository.upsert_many([changed]).updated == 1
    assert repository.upsert_many([candle(timestamp, source="provider-b")]).inserted == 1
    assert repository.count(symbol="EURUSD", timeframe="M1") == 2


def test_invalid_batch_is_rejected_without_partial_insert(db_session):
    rows = [
        candle(datetime(2026, 8, 21, 10, tzinfo=UTC)),
        {**candle(datetime(2026, 8, 21, 10, 1, tzinfo=UTC)), "low": Decimal("-1")},
    ]
    provider = FakeProvider(rows)
    with pytest.raises(DataValidationError):
        MarketDataIngestionService(db_session, provider).import_historical(
            "EURUSD", "M1", rows[0]["timestamp"], rows[-1]["timestamp"],
        )
    assert CandleRepository(db_session).count(symbol="EURUSD", timeframe="M1") == 0
    audit = db_session.query(MarketDataIngestion).one()
    assert audit.status == "FAILED"


def test_incremental_update_starts_after_latest_closed_candle(db_session):
    latest = candle(datetime(2026, 8, 21, 10, tzinfo=UTC), source="fake")
    CandleRepository(db_session).upsert_many([latest])
    provider = FakeProvider([])
    MarketDataIngestionService(db_session, provider).update_incremental(
        "EURUSD", "M1", end=datetime(2026, 8, 21, 10, 5, tzinfo=UTC),
    )
    assert provider.requests[0][2] == datetime(2026, 8, 21, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("source_tf", "target_tf", "count", "minutes"),
    [("M1", "M5", 5, 1), ("M5", "M15", 3, 5), ("M15", "M30", 2, 15), ("M15", "H1", 4, 15),
     ("H1", "H4", 4, 60), ("H4", "D1", 6, 240)],
)
def test_controlled_resampling_all_supported_conversions(source_tf, target_tf, count, minutes):
    start = datetime(2026, 8, 21, tzinfo=UTC)
    rows = [candle(start + timedelta(minutes=minutes * index), source_tf, price=str(1 + index / 100)) for index in range(count)]
    output = MarketDataResampler().resample(rows, source_tf, target_tf, as_of=start + timedelta(minutes=minutes * count))
    assert len(output) == 1
    assert output[0]["open"] == rows[0]["open"]
    assert output[0]["close"] == rows[-1]["close"]
    assert output[0]["volume"] == Decimal("10") * count
    assert output[0]["resampling_method"] == "UTC_COMPLETE_BUCKET_OHLCV_V1"


def test_h1_candle_is_not_available_at_1015_from_m15():
    start = datetime(2026, 8, 21, 10, tzinfo=UTC)
    rows = [candle(start + timedelta(minutes=15 * index), "M15") for index in range(4)]
    assert MarketDataResampler().resample(rows, "M15", "H1", as_of=start + timedelta(minutes=15)) == []
    assert len(MarketDataResampler().resample(rows, "M15", "H1", as_of=start + timedelta(hours=1))) == 1


def test_backtest_loader_excludes_unclosed_and_not_yet_observable_candles(db_session):
    start = datetime(2026, 8, 21, 10, tzinfo=UTC)
    rows = [candle(start + timedelta(hours=index), "H1") for index in range(2)]
    rows.append({**candle(start + timedelta(hours=2), "H1"), "is_closed": False})
    CandleRepository(db_session).upsert_many(rows)
    assert BacktestDataLoader(db_session).load("EURUSD", "H1", as_of=start + timedelta(minutes=15)) == []
    visible = BacktestDataLoader(db_session).load("EURUSD", "H1", as_of=start + timedelta(hours=2))
    assert [row.timestamp.hour for row in visible] == [10, 11]


def test_backtest_loader_never_exposes_future_t_plus_one(db_session):
    at_t = datetime(2026, 8, 21, 10, tzinfo=UTC)
    CandleRepository(db_session).upsert_many([
        candle(at_t - timedelta(minutes=1)), candle(at_t + timedelta(minutes=1)),
    ])
    visible = BacktestDataLoader(db_session).load("EURUSD", "M1", as_of=at_t)
    assert [BacktestDataLoader._aware(row.timestamp) for row in visible] == [at_t - timedelta(minutes=1)]


def test_market_regime_loads_native_database_timeframe_with_as_of(db_session):
    start = datetime(2026, 8, 21, 10, tzinfo=UTC)
    CandleRepository(db_session).upsert_many([
        candle(start, "H1", source="twelve_data"),
        candle(start + timedelta(hours=4), "H4", source="twelve_data"),
    ])
    snapshot = MarketRegimeService(db_session).calculate("EURUSD", as_of=start + timedelta(hours=1))
    assert "H1" not in snapshot.trend_matrix.missing_timeframes
    assert "H4" in snapshot.trend_matrix.missing_timeframes


def test_gap_detection_classifies_weekend_and_weekday():
    friday = candle(datetime(2026, 8, 21, 21, tzinfo=UTC), "H1")
    sunday = candle(datetime(2026, 8, 23, 22, tzinfo=UTC), "H1")
    weekend = detect_market_data_gaps([friday, sunday])
    assert weekend[0].reason == "FX_WEEKEND_OR_MARKET_CLOSED"
    weekday = detect_market_data_gaps([
        candle(datetime(2026, 8, 24, 10, tzinfo=UTC), "M15"),
        candle(datetime(2026, 8, 24, 11, tzinfo=UTC), "M15"),
    ])
    assert weekday[0].expected_candles == 3
    assert weekday[0].reason == "MISSING_MARKET_CANDLES"


def test_freshness_status():
    now = datetime(2026, 8, 24, 12, tzinfo=UTC)
    fresh = calculate_freshness("EURUSD", "M1", candle(now - timedelta(seconds=30)), threshold_seconds=60, now=now)
    stale = calculate_freshness("EURUSD", "M1", candle(now - timedelta(seconds=90)), threshold_seconds=60, now=now)
    assert fresh.status.value == "FRESH"
    assert stale.status.value == "STALE"


def test_market_data_api_health_latest_gaps_readiness_and_providers(client, db_session):
    timestamp = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=2)
    CandleRepository(db_session).upsert_many([candle(timestamp)])
    assert client.get("/api/market-data/latest", params={"symbol": "EURUSD", "timeframe": "M1"}).status_code == 200
    assert client.get("/api/market-data/health", params={"symbol": "EURUSD", "timeframe": "M1"}).json()["count"] == 1
    assert client.get("/api/market-data/gaps").status_code == 200
    readiness = client.get("/api/market-data/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["symbols"]["EURUSD"]["M1"]["status"] in {"READY", "PARTIAL"}
    providers = client.get("/api/market-data/providers")
    assert providers.status_code == 200
    assert "api_key" not in providers.text.lower()


def test_real_data_readiness_does_not_count_sample_csv(db_session):
    timestamp = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=2)
    CandleRepository(db_session).upsert_many([candle(timestamp, source="local_csv")])
    report = MarketDataHealthService(db_session).health("EURUSD", "M1")
    assert report["count"] == 0
    assert report["status"] == "MISSING"


class FakeProvider(BaseMarketDataProvider):
    name = "fake"
    supported_symbols = ("EURUSD",)
    supported_timeframes = ("M1",)

    def __init__(self, rows):
        self.rows = rows
        self.requests = []

    def connect(self):
        return None

    def disconnect(self):
        return None

    def fetch_historical(self, symbol, timeframe, start, end):
        self.requests.append((symbol, timeframe, start, end))
        return self.rows

    def fetch_latest(self, symbol, timeframe):
        return self.rows[-1] if self.rows else None

    def fetch_incremental(self, symbol, timeframe, start, end=None):
        return self.fetch_historical(symbol, timeframe, start, end)

    def health_check(self):
        return ProviderStatus(self.name, ProviderHealth.HEALTHY, None, None, None, self.supported_symbols, self.supported_timeframes)
