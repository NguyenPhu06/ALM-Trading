from data_sources.validators import MarketQualityValidator,QualityStatus
from tests.phase7_helpers import NOW,candle
def test_quality_invalid_blocks_bad_ohlc():
    bad={**candle(),"high":.9}
    assert MarketQualityValidator().evaluate([bad],symbol="EURUSD",timeframe="M5",as_of=NOW).status is QualityStatus.INVALID
