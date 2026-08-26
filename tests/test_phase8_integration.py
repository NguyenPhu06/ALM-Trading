from paper import OrderType,calculate_performance
from tests.phase8_helpers import PRED,QUOTE,RISK_OK,request,running_service
from tests.phase7_helpers import NOW
from database.repositories import PaperTradingRepository
from database.models import PaperAccountRecord,PaperOrderRecord,PaperTradeJournalRecord
from paper import PaperTradingService
def test_market_intelligence_nn_strategy_risk_paper_dca_exit_journal_performance_flow():
    service=running_service()
    entry=service.enter(request(),quote=QUOTE,setup_status="EXECUTABLE_SIMULATION",risk_decision=RISK_OK,data_quality="VALID",provider_status="ONLINE",prediction=PRED,reasons=("WHY_ENTRY:MTF_LIQUIDITY_NN_ALIGNED",))
    assert entry.accepted;pid=entry.order.position_id
    assert service.dca(pid,request(OrderType.DCA,position_id=pid),quote=QUOTE,market_regime="TRENDING",structure_state="HL_VALID",risk_state="ALLOWED").accepted
    service.mark(pid,1.105,NOW);service.close_position(pid,price=1.11,timestamp=NOW,reason=("WHY_EXIT:TIME_CHECKPOINT",))
    journal=service.journals[-1];metrics=calculate_performance([{**journal.final_result,"dca_depth":len(journal.dca_history)}])
    assert journal.final_result and journal.dca_history and metrics.total_trades==1 and not hasattr(service,"broker")

def test_paper_worker_persists_account_order_and_journal(db_session):
    service=PaperTradingService(repository=PaperTradingRepository(db_session));service.start()
    result=service.enter(request(),quote=QUOTE,setup_status="EXECUTABLE_SIMULATION",risk_decision=RISK_OK,data_quality="VALID",provider_status="ONLINE",prediction=PRED);pid=result.order.position_id
    service.close_position(pid,price=1.11,timestamp=NOW)
    assert db_session.query(PaperAccountRecord).count()==1 and db_session.query(PaperOrderRecord).count()==1 and db_session.query(PaperTradeJournalRecord).count()==1
