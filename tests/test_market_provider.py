from data_sources.providers import MarketDataProvider,MockMarketDataProvider,TradingViewAdapter
from tests.phase7_helpers import mtf_rows,quote
def test_provider_contract_and_legal_tradingview_placeholder():
    provider=MockMarketDataProvider(mtf_rows(),quote());assert isinstance(provider,MarketDataProvider)
    assert provider.get_latest_quote("EURUSD")["mid_price"]==1.1001
    assert TradingViewAdapter().health_check().last_error=="LEGAL_API_UNAVAILABLE"
