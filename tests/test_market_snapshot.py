from data_sources.providers import MockMarketDataProvider
from data_sources.snapshot import RealMarketSnapshotEngine
from tests.phase7_helpers import NOW,mtf_rows,quote
def test_market_snapshot_has_mtf_quality_and_no_future_rows():
    result=RealMarketSnapshotEngine(MockMarketDataProvider(mtf_rows(),quote())).build("EURUSD",as_of=NOW)
    assert set(result.mtf_candles)=={"D1","H4","H1","M30","M15","M5"}
    assert result.strategy_allowed and result.institutional_proxy["provider_status"].value=="UNAVAILABLE"
