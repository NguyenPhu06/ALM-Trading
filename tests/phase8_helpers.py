from types import SimpleNamespace
from paper import *
from tests.phase7_helpers import NOW
QUOTE={"timestamp":NOW,"symbol":"EURUSD","bid":1.1,"ask":1.1002,"mid_price":1.1001,"source":"test"}
PRED={"prob_up":.7,"prob_down":.2,"prob_neutral":.1}
def request(order_type=OrderType.MARKET,source_timestamp=NOW,position_id=None):return PaperOrderRequest("EURUSD",Direction.LONG,order_type,1.,NOW,position_id=position_id,source_timestamp=source_timestamp)
def running_service():s=PaperTradingService();s.start();return s
RISK_OK=SimpleNamespace(risk_allowed=True)
