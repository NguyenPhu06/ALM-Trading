"""GET /market/snapshot (Phase 12 section 19)."""
import pytest

SECTIONS = ("symbol", "timestamp", "price", "spread", "sessions", "regime",
            "timeframes", "structure", "liquidity", "indicators",
            "neural_network", "strategy", "risk", "execution")


def test_the_endpoint_responds_before_any_cycle_has_run(client):
    body = client.get("/market/snapshot").json()
    assert body["data_quality"] == "UNAVAILABLE"
    assert body["data"]["available"] is False
    assert body["data"]["orders_sent"] == 0


def test_a_refresh_runs_a_cycle_and_returns_every_section(client, db_session):
    from tests.phase9_helpers import seed_market
    from tests.phase12_helpers import NOW

    seed_market(db_session, now=NOW)
    body = client.get("/market/snapshot?symbol=EURUSD&refresh=true").json()
    payload = body["data"]
    if payload.get("halted"):
        pytest.skip(f"cycle halted: {payload.get('reasons')}")
    for section in SECTIONS:
        assert section in payload, section
    assert payload["orders_sent"] == 0


def test_the_snapshot_reports_observation_mode(client, db_session):
    from tests.phase9_helpers import seed_market
    from tests.phase12_helpers import NOW

    seed_market(db_session, now=NOW)
    payload = client.get("/market/snapshot?refresh=true").json()["data"]
    assert payload["observation_mode"] is True


def test_the_endpoint_is_read_only(client):
    assert client.post("/market/snapshot").status_code == 405


def test_the_snapshot_never_returns_a_credential(client, db_session):
    response = client.get("/market/snapshot?refresh=true")
    text = response.text.lower()
    assert not any(token in text for token in ("password", "secret", "credential"))


def test_a_stored_snapshot_is_returned_without_re_running_the_pipeline(client, db_session):
    from tests.phase9_helpers import seed_market
    from tests.phase12_helpers import NOW

    seed_market(db_session, now=NOW)
    first = client.get("/market/snapshot?refresh=true").json()["data"]
    if first.get("halted"):
        pytest.skip("no MT5 terminal on this host; the cycle halts at account validation")
    body = client.get("/market/snapshot").json()
    assert body["data"].get("cycle_id")
    assert body["data"]["orders_sent"] == 0


def test_the_observation_cycle_endpoint_sends_nothing(client, db_session):
    from tests.phase9_helpers import seed_market
    from tests.phase12_helpers import NOW

    seed_market(db_session, now=NOW)
    body = client.post("/observation/cycle?symbol=EURUSD").json()
    assert body["orders_sent"] == 0
    assert body["automated_trading"] is False


def test_the_observation_status_endpoint_reports_no_automation(client):
    payload = client.get("/observation/status").json()["data"]
    assert payload["observation_mode"] is True
    assert payload["automated_trading"] is False
    assert payload["orders_sent"] == 0


def test_the_performance_endpoint_labels_itself_as_forward_observation(client):
    payload = client.get("/observation/performance").json()["data"]
    assert payload["orders_sent"] == 0
    assert "no order was ever placed" in payload["note"].lower()
