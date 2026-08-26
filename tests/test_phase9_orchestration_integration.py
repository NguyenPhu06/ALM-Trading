"""End to end: data -> intelligence -> strategy -> risk -> paper -> persistence -> alert -> dashboard.

Every dashboard assertion here reads data that the orchestration loop generated in
the same test. Before Phase 9's repair nothing populated these panels at all.
"""
import pytest

from database.models import DashboardAlertRecord, PaperOrderRecord, StrategyDecisionRecord
from database.repositories import PaperTradingRepository
from orchestration import OrchestrationCycle, Stage
from paper.service import bound_repository
from tests.phase9_helpers import NOW, StubInference, seed_market


@pytest.fixture()
def service():
    from api.main import paper_service

    paper_service.__init__()
    paper_service.start()
    yield paper_service
    paper_service.__init__()


def run_loop(db_session, service, *, inference=None):
    with bound_repository(service, PaperTradingRepository(db_session)):
        cycle = OrchestrationCycle(db_session, paper_service=service, now=NOW,
                                   inference=inference or StubInference())
        return cycle.run("EURUSD")


def test_the_loop_populates_every_dashboard_panel_it_feeds(client, db_session, service):
    seed_market(db_session)
    result = run_loop(db_session, service)
    assert result.stage is Stage.COMPLETED

    mtf = client.get("/dashboard/mtf/EURUSD").json()
    assert mtf["data_quality"] == "VALID"
    assert mtf["data"]["timeframes"]["D1"]["trend"] != "UNAVAILABLE"
    assert mtf["data"]["alignment"]["status"] in {"ALIGNED", "PARTIALLY_ALIGNED", "CONFLICT"}

    strategy = client.get("/dashboard/strategy/EURUSD").json()
    assert strategy["data_quality"] == "VALID"
    assert strategy["data"]["decision"]["decision"] == "SIMULATE"
    assert strategy["data"]["setup"]["status"] == "EXECUTABLE_SIMULATION"

    ai = client.get("/dashboard/ai/EURUSD").json()
    assert ai["data"]["model_status"] == "ONLINE"
    assert ai["data"]["prediction"]["prob_up"] == pytest.approx(0.72)

    positions = client.get("/dashboard/positions").json()
    assert positions["data_quality"] == "VALID"
    assert positions["data"]["items"][0]["symbol"] == "EURUSD"

    alerts = client.get("/dashboard/alerts").json()
    types = {item["alert_type"] for item in alerts["data"]["items"]}
    assert {"STRATEGY_READY", "PAPER_ENTRY"} <= types
    assert alerts["data"]["unread"] >= 2

    overview = client.get("/dashboard/overview").json()["data"]
    assert overview["system"]["strategy"] == "ONLINE"
    assert overview["system"]["ai_model"] == "ONLINE"
    assert overview["unread_alerts"] >= 2


def test_dashboard_freshness_reflects_the_candle_the_loop_used(client, db_session, service):
    seed_market(db_session)
    run_loop(db_session, service)
    body = client.get("/dashboard/positions").json()
    assert body["last_update"] is not None
    assert body["data_age_seconds"] is not None and body["data_age_seconds"] >= 0


def test_persistence_survives_a_restart_of_the_paper_service(client, db_session, service):
    seed_market(db_session)
    run_loop(db_session, service)
    assert db_session.query(PaperOrderRecord).count() == 1

    from paper import PaperTradingService

    restarted = PaperTradingService().restore(PaperTradingRepository(db_session))
    assert len(restarted.positions) == 1
    assert restarted.orders and restarted.journals


def test_without_a_model_the_dashboard_shows_an_invalidated_setup_and_no_position(
    client, db_session, service,
):
    seed_market(db_session)
    with bound_repository(service, PaperTradingRepository(db_session)):
        cycle = OrchestrationCycle(db_session, paper_service=service, now=NOW)   # no inference
        result = cycle.run("EURUSD")

    assert result.decision == "INVALIDATE" and "MODEL_UNAVAILABLE" in result.reason_codes
    strategy = client.get("/dashboard/strategy/EURUSD").json()
    assert strategy["data"]["decision"]["decision"] == "INVALIDATE"
    assert client.get("/dashboard/positions").json()["data"]["items"] == []
    assert client.get("/dashboard/ai/EURUSD").json()["data"]["model_status"] == "OFFLINE"
    assert db_session.query(DashboardAlertRecord).one().alert_type == "STRATEGY_INVALIDATED"


def test_a_kill_switch_block_is_visible_on_the_risk_panel_and_in_alerts(client, db_session, service):
    seed_market(db_session)
    service.risk.kill_switch.activate()
    result = run_loop(db_session, service)

    assert not result.executed.accepted
    risk = client.get("/dashboard/risk").json()["data"]
    assert risk["kill_switch"] is True and risk["risk_state"] == "BLOCKED"
    severities = {row.alert_type: row.severity for row in db_session.query(DashboardAlertRecord).all()}
    assert severities.get("RISK_BLOCK") == "CRITICAL"
    assert client.get("/dashboard/positions").json()["data"]["items"] == []


def test_closing_the_loops_position_through_the_api_completes_the_journal(client, db_session, service):
    seed_market(db_session)
    result = run_loop(db_session, service)
    position_id = result.executed.order.position_id

    assert client.post(f"/paper/close-position/{position_id}?price=1.12").status_code == 200

    journal = client.get("/dashboard/journal").json()
    closed = [item for item in journal["data"]["items"] if item["final_result"]]
    assert closed and closed[0]["trade_id"] == position_id
    assert client.get("/dashboard/performance").json()["data"]["overall"]["total_trades"] == 1
    types = {row.alert_type for row in db_session.query(DashboardAlertRecord).all()}
    assert "EXIT_TRIGGER" in types
    assert db_session.query(StrategyDecisionRecord).count() == 1
