from paper import OrderType
from tests.phase8_helpers import PRED,QUOTE,RISK_OK,request,running_service
def test_dca_is_logged_and_finite():
    service=running_service();entry=service.enter(request(),quote=QUOTE,setup_status="EXECUTABLE_SIMULATION",risk_decision=RISK_OK,data_quality="VALID",provider_status="ONLINE",prediction=PRED)
    pid=entry.order.position_id;result=service.dca(pid,request(OrderType.DCA,position_id=pid),quote=QUOTE,market_regime="TRENDING",structure_state="VALID",risk_state="ALLOWED")
    assert result.accepted and service.dca_events[0].reason.startswith("WHY_DCA")
