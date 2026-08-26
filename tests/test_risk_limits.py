from paper import PaperRiskEngine
def test_risk_rejects_exposure_spread_news_and_quality():
    r=PaperRiskEngine(max_exposure=10,max_spread=.001).evaluate(exposure=10,spread=.002,news_risk="HIGH",data_quality="INVALID",provider_status="OFFLINE")
    assert not r.allowed and {"MAXIMUM_EXPOSURE","SPREAD_TOO_WIDE","HIGH_IMPACT_EVENT_NEARBY","DATA_QUALITY_INVALID","PROVIDER_UNAVAILABLE"}<=set(r.rejection_reasons)
