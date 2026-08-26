from paper import Direction,OrderType,PaperOrderRequest
from tests.phase7_helpers import NOW
def test_paper_order_contract_has_no_broker_fields():
    order=PaperOrderRequest("EURUSD",Direction.LONG,OrderType.LIMIT,1,NOW,requested_price=1.1)
    assert order.order_type is OrderType.LIMIT and not hasattr(order,"broker_account")
