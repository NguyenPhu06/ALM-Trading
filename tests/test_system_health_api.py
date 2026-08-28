"""GET /system/health (Phase 12 section 20)."""
import pytest

from observation.health import COMPONENTS

VALID_STATES = {"HEALTHY", "DEGRADED", "FAILED", "UNKNOWN"}


def test_every_documented_component_is_reported(client):
    payload = client.get("/system/health").json()["data"]
    for name in COMPONENTS:
        assert name in payload, name


def test_every_component_reports_a_valid_state(client):
    payload = client.get("/system/health").json()["data"]
    for name in COMPONENTS:
        assert payload[name]["state"] in VALID_STATES, name


def test_an_overall_state_is_reported(client):
    payload = client.get("/system/health").json()["data"]
    assert payload["state"] in VALID_STATES


def test_the_api_reports_itself_healthy(client):
    payload = client.get("/system/health").json()["data"]
    assert payload["api"]["state"] == "HEALTHY"


def test_mt5_is_reported_and_carries_account_status(client):
    payload = client.get("/system/health").json()["data"]
    assert payload["mt5"]["state"] in VALID_STATES
    assert "account_status" in payload["mt5"]


def test_execution_reports_the_safety_posture(client):
    detail = client.get("/system/health").json()["data"]["execution"]
    assert detail["observation_mode"] is True
    assert detail["demo_trading_enabled"] is False
    assert detail["mt5_execution_enabled"] is False
    assert detail["kill_switch"] is True
    assert detail["automated_trading"] is False


def test_components_with_no_evidence_are_unknown_not_healthy(client):
    """A component we cannot see must never be reported as healthy."""
    payload = client.get("/system/health").json()["data"]
    assert payload["nn"]["state"] == "UNKNOWN"


def test_the_endpoint_is_read_only(client):
    assert client.post("/system/health").status_code == 405


def test_the_endpoint_never_returns_a_credential(client):
    text = client.get("/system/health").text.lower()
    assert not any(token in text for token in ("password", "secret", "credential"))
