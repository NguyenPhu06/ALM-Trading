from datetime import timedelta
from paper import PaperExecutionEngine
from tests.phase8_helpers import QUOTE,request
from tests.phase7_helpers import NOW
def test_paper_execution_rejects_future_source():
    r=PaperExecutionEngine().execute(request(source_timestamp=NOW+timedelta(seconds=1)),quote=QUOTE);assert not r.accepted and r.rejection_reason=="FUTURE_DATA_REJECTED"
