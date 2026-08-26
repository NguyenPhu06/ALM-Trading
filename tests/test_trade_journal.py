from tests.phase8_helpers import PRED,QUOTE,RISK_OK,request,running_service
from tests.phase7_helpers import NOW
def test_entry_exit_journal_contains_explanations_and_net_result():
    service=running_service();entry=service.enter(request(),quote=QUOTE,setup_status="EXECUTABLE_SIMULATION",risk_decision=RISK_OK,data_quality="VALID",provider_status="ONLINE",prediction=PRED,reasons=("WHY_ENTRY:TEST",));pid=entry.order.position_id
    service.close_position(pid,price=1.11,timestamp=NOW,reason=("WHY_EXIT:TEST",));journal=service.journals[-1]
    assert journal.entry_reason==("WHY_ENTRY:TEST",) and journal.exit_reason==("WHY_EXIT:TEST",) and "net_pnl" in journal.final_result
