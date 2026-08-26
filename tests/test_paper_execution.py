from paper_execution import PaperExecutionProvider,PaperOrderStatus
from tests.phase7_helpers import NOW
from paper import ExecutionConfig,PaperExecutionEngine
from tests.phase8_helpers import QUOTE,request
def test_paper_execution_never_routes_to_broker():
    provider=PaperExecutionProvider();order=provider.submit_order(symbol="EURUSD",direction="LONG",entry=1.1,size=1,stop=1.09,take_profit=1.12,timestamp=NOW,strategy_version="phase6",model_version=None)
    assert provider.get_positions()==(order,);assert provider.close_order(order.order_id).status is PaperOrderStatus.CLOSED
    assert not hasattr(provider,"broker")

def test_phase8_execution_uses_ask_slippage_commission_and_source():
    result=PaperExecutionEngine(ExecutionConfig(fixed_slippage=.0001,commission_per_trade=1)).execute(request(),quote=QUOTE)
    assert result.accepted and result.order.executed_price>QUOTE["ask"]
    assert result.order.commission==1 and result.order.spread_source=="PROVIDER_BID_ASK"
