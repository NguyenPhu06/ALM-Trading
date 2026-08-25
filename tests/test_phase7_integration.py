from data_sources.ingestion import MarketDataIngestionService
from data_sources.providers import MockMarketDataProvider
from data_sources.gateway import DatabaseMarketDataProvider
from data_sources.snapshot import RealMarketSnapshotEngine
from paper_execution import PaperExecutionProvider
from tests.phase7_helpers import NOW,candle
def test_provider_database_snapshot_to_paper_simulation(db_session):
    row=candle(source="mock-real");provider=MockMarketDataProvider([row]);provider.name="mock-real"
    report=MarketDataIngestionService(db_session,provider).import_historical("EURUSD","M5",NOW,NOW);assert report.rows_inserted==1
    snapshot=RealMarketSnapshotEngine(DatabaseMarketDataProvider(db_session)).build("EURUSD",as_of=NOW)
    assert snapshot.mtf_candles["M5"]
    paper=PaperExecutionProvider();order=paper.submit_order(symbol="EURUSD",direction="LONG",entry=1.1,size=1,stop=None,take_profit=None,timestamp=NOW,strategy_version="phase6",model_version=None)
    assert paper.get_positions()==(order,)
