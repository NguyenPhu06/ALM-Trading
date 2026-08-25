from data_sources.providers.context import EconomicEvent,NewsRiskEngine,NewsRiskState
from tests.phase7_helpers import NOW
def test_high_impact_event_creates_news_risk():
    event=EconomicEvent("CPI","USD","HIGH",NOW,source="authorized")
    assert NewsRiskEngine().evaluate([event],timestamp=NOW,currencies=("EUR","USD")) is NewsRiskState.HIGH
