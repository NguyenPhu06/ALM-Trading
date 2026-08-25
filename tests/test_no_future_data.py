from datetime import timedelta
from data_sources.providers import MockMarketDataProvider
from data_sources.snapshot import RealMarketSnapshotEngine
from tests.phase7_helpers import NOW,candle,mtf_rows,quote
def test_future_candle_cannot_enter_real_snapshot():
    rows=mtf_rows()+[candle(NOW+timedelta(minutes=5),"M5")];future_quote={**quote(),"timestamp":NOW+timedelta(seconds=1)}
    result=RealMarketSnapshotEngine(MockMarketDataProvider(rows,future_quote)).build("EURUSD",as_of=NOW)
    assert all(row["timestamp"]<=NOW for row in result.mtf_candles["M5"])
    assert result.quote is None and "FUTURE_QUOTE_REJECTED" in result.reasons
