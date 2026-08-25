from paper_execution import PaperExecutionProvider,PaperOrderStatus
from tests.phase7_helpers import NOW
def test_paper_execution_never_routes_to_broker():
    provider=PaperExecutionProvider();order=provider.submit_order(symbol="EURUSD",direction="LONG",entry=1.1,size=1,stop=1.09,take_profit=1.12,timestamp=NOW,strategy_version="phase6",model_version=None)
    assert provider.get_positions()==(order,);assert provider.close_order(order.order_id).status is PaperOrderStatus.CLOSED
    assert not hasattr(provider,"broker")
