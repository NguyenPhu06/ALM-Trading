from paper import PaperAccount
from tests.phase7_helpers import NOW
def test_drawdown_uses_peak_equity():
    a=PaperAccount();a.mark(100,NOW);a.mark(-100,NOW);assert round(a.max_drawdown,4)==round(200/1100,4)
