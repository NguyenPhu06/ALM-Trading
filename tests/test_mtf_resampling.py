from datetime import timedelta
from data_sources.resampler import MarketDataResampler
from tests.phase7_helpers import NOW,candle
def test_m5_resamples_only_complete_m15_bucket():
    rows=[candle(NOW+timedelta(minutes=5*i),"M5") for i in range(3)]
    assert MarketDataResampler().resample(rows,"M5","M15",as_of=NOW+timedelta(minutes=10))==[]
    assert len(MarketDataResampler().resample(rows,"M5","M15",as_of=NOW+timedelta(minutes=15)))==1
