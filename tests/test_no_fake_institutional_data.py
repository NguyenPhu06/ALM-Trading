from data_sources.providers.context import Availability,InstitutionalPositionProvider
def test_missing_institutional_source_stays_unavailable():
    result=InstitutionalPositionProvider().get_observation("EURUSD")
    assert result.provider_status is Availability.UNAVAILABLE and result.institutional_pressure_proxy is None and result.is_proxy
