from tests.phase8_helpers import PRED,QUOTE,RISK_OK,request,running_service
def test_invalid_data_or_offline_provider_blocks_entry():
    result=running_service().enter(request(),quote=QUOTE,setup_status="EXECUTABLE_SIMULATION",risk_decision=RISK_OK,data_quality="INVALID",provider_status="OFFLINE",prediction=PRED)
    assert not result.accepted and result.rejection_reason in {"DATA_QUALITY_INVALID","PROVIDER_UNAVAILABLE"}
