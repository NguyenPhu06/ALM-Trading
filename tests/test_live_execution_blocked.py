import pytest
from paper import LiveExecutionBlocked,PaperExecutionEngine,TradingEnvironment
from tests.phase8_helpers import QUOTE,request
def test_live_environment_is_always_blocked():
    with pytest.raises(LiveExecutionBlocked):PaperExecutionEngine().execute(request(),quote=QUOTE,environment=TradingEnvironment.LIVE)
