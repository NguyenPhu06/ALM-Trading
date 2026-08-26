from paper import DailyRiskManager
from tests.phase7_helpers import NOW
def test_daily_loss_pauses_new_entries():
    manager=DailyRiskManager(.03);manager.update(NOW,1000);assert manager.update(NOW,960) and manager.paused
