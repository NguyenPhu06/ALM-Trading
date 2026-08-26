def test_observation_pipeline_reaches_dashboard_without_live_execution(client):
    market=client.get('/dashboard/market/EURUSD').json();strategy=client.get('/dashboard/strategy/EURUSD').json();risk=client.get('/dashboard/risk').json();positions=client.get('/dashboard/positions').json()
    assert market['timestamp'] and strategy['data']['decision'] and risk['data']['risk_state'] and 'items' in positions['data']
    assert client.post('/live/order').status_code==404 and client.post('/demo/order').status_code==404
