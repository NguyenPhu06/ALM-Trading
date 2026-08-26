from datetime import timedelta
from paper import PaperMarketReplay
from tests.phase7_helpers import NOW,candle
def test_replay_exposes_only_past_history():
    seen=[]
    def handler(row,history):seen.append(len(history));return "ENTRY" if not history else "EXIT"
    rows=[candle(NOW+timedelta(minutes=5*i),"M5") for i in range(2)];steps=PaperMarketReplay().run(rows,handler)
    assert seen==[0,1] and [s.action for s in steps]==["ENTRY","EXIT"]
