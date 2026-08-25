from data_sources.providers import MockMarketDataProvider,ProviderHealth
def test_mock_provider_reports_online_equivalent_health():
    assert MockMarketDataProvider([]).health_check().status is ProviderHealth.HEALTHY
