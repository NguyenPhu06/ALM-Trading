def test_all_dashboard_endpoints_have_observation_envelope(client):
    endpoints=['/dashboard/overview','/dashboard/market/EURUSD','/dashboard/mtf/EURUSD','/dashboard/liquidity/EURUSD','/dashboard/indicators/EURUSD','/dashboard/ai/EURUSD','/dashboard/strategy/EURUSD','/dashboard/risk','/dashboard/positions','/dashboard/performance','/dashboard/journal','/dashboard/alerts','/dashboard/timeline/EURUSD']
    for endpoint in endpoints:
        response=client.get(endpoint);assert response.status_code==200,endpoint;body=response.json();assert {'timestamp','source','version','data_quality'}<=body.keys();assert client.post(endpoint).status_code==405
def test_overview_symbols_and_mtf_are_backend_driven(client):
    overview=client.get('/dashboard/overview').json()['data'];assert 'EURUSD' in overview['symbols'] and overview['timeframes']==['D1','H4','H1','M30','M15','M5']
