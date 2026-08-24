from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from database.models import StructureEvent
from database.repositories import CandleRepository
from config.settings import ROOT
from data_sources.market_data import LocalCsvProvider
from data_sources.normalizer import CandleNormalizer
from features.candles import candle_close_time
from features.liquidity import LiquidityEngine
from features.mtf import MTFAlignmentEngine, MTFResampler
from features.pipeline import Phase1BPipeline
from features.session import SessionEngine, SessionName
from features.snapshot import create_feature_snapshot
from features.structure import MarketStructureEngine, StructureEventData, SwingDetector
from tests.fixtures import deterministic_m15_candles


def test_unclosed_candle_cannot_create_swing_bos_choch_or_sweep():
    rows = deterministic_m15_candles(6)
    rows[1].update(high=Decimal("1.1200"), close=Decimal("1.1100"))
    rows[2].update(high=Decimal("1.1150"), low=Decimal("1.0900"), close=Decimal("1.1000"))
    rows[3].update(high=Decimal("1.1100"), low=Decimal("1.0800"), close=Decimal("1.0900"))
    rows[4].update(high=Decimal("1.1150"), close=Decimal("1.1000"))
    closed_prefix = rows[:5]
    rows[5].update(high=Decimal("1.1300"), low=Decimal("1.0700"), close=Decimal("1.1250"), is_closed=False)

    structure_engine = MarketStructureEngine(swing_left_bars=1, swing_right_bars=2)
    liquidity_engine = LiquidityEngine(swing_left_bars=1, swing_right_bars=2)
    assert structure_engine.calculate(rows) == structure_engine.calculate(closed_prefix)
    assert liquidity_engine.calculate(rows) == liquidity_engine.calculate(closed_prefix)


def test_closed_state_defaults_safe_for_live_and_true_for_historical_csv():
    raw = {
        "timestamp": "2026-08-20T10:00:00Z", "symbol": "EURUSD", "timeframe": "M15",
        "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.1", "volume": "1",
    }
    assert CandleNormalizer().normalize(raw, source="live_candidate")["is_closed"] is False
    imported = LocalCsvProvider(ROOT / "data/sample/EURUSD_M15_sample.csv").get_candles("EURUSD", "M15")
    assert imported and all(candle["is_closed"] is True for candle in imported)


def test_right_two_swing_is_confirmed_at_t_plus_two_close_only():
    rows = deterministic_m15_candles(4)
    rows[0]["high"], rows[1]["high"], rows[2]["high"], rows[3]["high"] = map(Decimal, ("1.10", "1.20", "1.15", "1.14"))
    detector = SwingDetector(left_bars=1, right_bars=2)
    assert not any(point.index == 1 for point in detector.detect(rows, as_of_index=2))
    swing = next(point for point in detector.detect(rows, as_of_index=3) if point.index == 1)
    assert swing.confirmation_timestamp == candle_close_time(rows[3])
    assert swing.confirmation_timestamp > rows[3]["timestamp"]


def test_mtf_resampling_ohlcv_and_complete_close_times():
    rows = deterministic_m15_candles(96)
    resampler = MTFResampler()
    h1 = resampler.resample(rows, "H1")
    h4 = resampler.resample(rows, "H4")
    d1 = resampler.resample(rows, "D1")
    assert (len(h1), len(h4), len(d1)) == (24, 6, 1)
    first = h1[0]
    assert first.open == rows[0]["open"] and first.close == rows[3]["close"]
    assert first.high == max(row["high"] for row in rows[:4])
    assert first.low == min(row["low"] for row in rows[:4])
    assert first.volume == sum(row["volume"] for row in rows[:4])
    assert first.open_time == rows[0]["timestamp"]
    assert first.close_time == rows[0]["timestamp"] + timedelta(hours=1)
    assert first.is_closed is True and first.timeframe == "H1"


def test_resampler_excludes_incomplete_open_or_future_bucket():
    rows = deterministic_m15_candles(4, start=datetime(2026, 8, 20, 10, tzinfo=timezone.utc))
    resampler = MTFResampler()
    assert resampler.resample(rows, "H1", as_of=datetime(2026, 8, 20, 10, 45, tzinfo=timezone.utc)) == []
    assert len(resampler.resample(rows, "H1", as_of=datetime(2026, 8, 20, 11, tzinfo=timezone.utc))) == 1
    rows[-1]["is_closed"] = False
    assert resampler.resample(rows, "H1") == []


def test_mtf_alignment_uses_only_last_confirmed_htf_state():
    rows = deterministic_m15_candles(4, start=datetime(2026, 8, 20, 10, tzinfo=timezone.utc))
    h1_confirmed = StructureEventData(
        datetime(2026, 8, 20, 11, tzinfo=timezone.utc), "EURUSD", "H1",
        "BEARISH_BOS", "BEARISH", Decimal("1.1"),
        datetime(2026, 8, 20, 11, tzinfo=timezone.utc),
    )
    h1_future = StructureEventData(
        datetime(2026, 8, 20, 12, tzinfo=timezone.utc), "EURUSD", "H1",
        "BULLISH_CHOCH", "BULLISH", Decimal("1.2"),
        datetime(2026, 8, 20, 12, tzinfo=timezone.utc),
    )
    engine = MTFAlignmentEngine()
    before = engine.state_at(rows[2], {"H1": [h1_confirmed, h1_future]})
    at_close = engine.state_at(rows[3], {"H1": [h1_confirmed, h1_future]})
    assert before.states["H1"].last_event_type is None
    assert at_close.states["H1"].last_event_type == "BEARISH_BOS"
    assert at_close.states["H1"].last_event_timestamp == h1_confirmed.event_timestamp


def test_snapshot_at_t_is_identical_after_future_candles_are_appended():
    rows = deterministic_m15_candles(12)
    prefix = rows[:8]
    structure_engine = MarketStructureEngine(swing_left_bars=1, swing_right_bars=2)
    liquidity_engine = LiquidityEngine(swing_left_bars=1, swing_right_bars=2)
    prefix_structure = structure_engine.calculate(prefix)
    prefix_liquidity = liquidity_engine.calculate(prefix)
    full_structure = structure_engine.calculate(rows)
    full_liquidity = liquidity_engine.calculate(rows)
    snapshot_before = create_feature_snapshot(prefix[-1], prefix_structure, prefix_liquidity)
    snapshot_after = create_feature_snapshot(prefix[-1], full_structure, full_liquidity)
    assert snapshot_after == snapshot_before


@pytest.mark.parametrize(
    ("hour", "expected"),
    [(1, SessionName.ASIA), (10, SessionName.LONDON), (20, SessionName.NEW_YORK), (14, SessionName.LONDON_NEW_YORK_OVERLAP)],
)
def test_all_configured_session_labels(hour, expected):
    assert SessionEngine(timezone="UTC").session_for(
        datetime(2026, 8, 20, hour, tzinfo=timezone.utc)
    ) is expected


def test_pipeline_filters_database_open_candle(db_session):
    repository = CandleRepository(db_session)
    rows = deterministic_m15_candles(5)
    rows[-1]["is_closed"] = False
    for row in rows:
        repository.add(row)
    pipeline = Phase1BPipeline(db_session)
    result = pipeline.run("EURUSD", "M15")
    assert result["candles"] == 5
    assert result["closed_candles"] == 4
    assert result["open_candles_excluded"] == 1
    assert len(pipeline.last_snapshots) == 4


def test_api_hides_event_whose_confirmation_is_later_than_event(client, db_session):
    valid_time = datetime(2026, 8, 20, 11, tzinfo=timezone.utc)
    db_session.add_all([
        StructureEvent(
            timestamp=valid_time, event_timestamp=valid_time, confirmation_timestamp=valid_time,
            symbol="EURUSD", timeframe="H1", event_type="BEARISH_BOS", direction="BEARISH",
            price=Decimal("1.1"), source="test",
        ),
        StructureEvent(
            timestamp=valid_time, event_timestamp=valid_time,
            confirmation_timestamp=valid_time + timedelta(hours=1),
            symbol="EURUSD", timeframe="H1", event_type="BULLISH_CHOCH", direction="BULLISH",
            price=Decimal("1.2"), source="malformed_test_fixture",
        ),
    ])
    db_session.commit()
    items = client.get("/api/structure", params={"symbol": "EURUSD", "timeframe": "H1"}).json()["items"]
    assert [item["event_type"] for item in items] == ["BEARISH_BOS"]
