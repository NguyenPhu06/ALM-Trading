from config.settings import get_settings
def test_dashboard_payload_never_contains_secrets(client):
    response=client.get('/dashboard/overview');text=response.text.lower();assert response.status_code==200
    assert all(token not in text for token in ('password','api_key','token','database_url','broker_credentials'))
    assert not get_settings().live_trading_enabled and not get_settings().demo_trading_enabled
