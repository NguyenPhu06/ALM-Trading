from paper import PaperAccount
from tests.phase7_helpers import NOW
def test_paper_account_tracks_net_equity_and_drawdown():
    account=PaperAccount(initial_balance=1000);account.mark(-100,NOW);assert account.equity==900 and account.max_drawdown==.1
    assert account.realize(20,2,1,NOW)==17 and account.balance==1017
