from __future__ import annotations

from config.settings import get_settings


PAYLOAD = {
    "symbol": "EURUSD", "timeframe": "15", "event": "LIQUIDITY_SWEEP",
    "direction": "BULLISH", "price": 1.1652, "timestamp": "2026-08-24T10:00:00Z",
}


def test_health_and_paginated_endpoints(client):
    health = client.get("/health")
    assert health.status_code == 200 and health.json() == {"status": "ok", "phase": "9"}


def test_phase8_paper_dashboard_and_controls_have_no_live_route(client):
    for endpoint in ("/paper/account","/paper/positions","/paper/orders","/paper/trades","/paper/equity","/paper/performance","/paper/risk","/paper/dashboard"):
        assert client.get(endpoint).status_code==200
    assert client.post("/paper/start").json()["environment"]=="PAPER"
    assert client.post("/paper/pause").status_code==200
    assert client.post("/paper/stop").status_code==200
    assert client.post("/live/order").status_code==404


def test_phase7_market_gateway_endpoints_are_read_only(client):
    endpoints=("/market/providers/status","/market/data-quality/EURUSD","/market/snapshot/EURUSD","/market/calendar","/market/cot/EURO%20FX","/intelligence/snapshot/EURUSD")
    for endpoint in endpoints:
        assert client.get(endpoint).status_code==200
        assert client.post(endpoint).status_code==405


def test_phase6_strategy_endpoints_are_read_only_and_empty_by_default(client):
    endpoints = (
        "/strategy/setup/latest", "/strategy/snapshot/EURUSD",
        "/strategy/decision/latest", "/strategy/backtest/latest", "/strategy/performance",
    )
    for endpoint in endpoints:
        assert client.get(endpoint).status_code == 404
        assert client.post(endpoint).status_code == 405
    for path in ("/api/candles", "/api/cot", "/api/tradingview/alerts"):
        response = client.get(path, params={"limit": 2, "offset": 0})
        assert response.status_code == 200
        assert response.json()["limit"] == 2
        assert isinstance(response.json()["items"], list)


def test_webhook_security_validation_and_insert(client):
    assert client.post("/webhooks/tradingview", json=PAYLOAD).status_code == 401
    headers = {"X-TradingView-Secret": get_settings().tradingview_webhook_secret}
    response = client.post("/webhooks/tradingview", json=PAYLOAD, headers=headers)
    assert response.status_code == 200
    alert_id = response.json()["id"]
    stored = client.get("/api/tradingview/alerts").json()["items"]
    assert any(row["id"] == alert_id for row in stored)
    assert "secret" not in stored[0]["payload_json"]


def test_payload_secret_fallback_is_not_stored(client):
    payload = {**PAYLOAD, "event": "CUSTOM", "secret": get_settings().tradingview_webhook_secret}
    response = client.post("/webhooks/tradingview", json=payload)
    assert response.status_code == 200
    stored = client.get("/api/tradingview/alerts").json()["items"][0]
    assert "secret" not in stored["payload_json"]


def test_webhook_rejects_unsupported_event(client):
    payload = {**PAYLOAD, "event": "UNKNOWN"}
    headers = {"X-TradingView-Secret": get_settings().tradingview_webhook_secret}
    assert client.post("/webhooks/tradingview", json=payload, headers=headers).status_code == 422


# ------------------------------------ Phase 16: controlled DEMO trading endpoints
# The running app uses the shipped defaults, so every one of these must report a
# blocked, observation-only posture. That is the point of the section: the API
# cannot be talked into executing.


def test_the_mode_endpoint_reports_observation_by_default(client):
    body = client.get("/execution/mode").json()["data"]
    assert body["mode"] == "OBSERVATION"
    assert body["sends_orders"] is False and body["live_enabled"] is False
    assert body["default_mode"] == "OBSERVATION"
    assert set(body["available_modes"]) == {"OBSERVATION", "SHADOW", "PAPER",
                                            "DEMO_MANUAL_APPROVAL", "DEMO_AUTOMATED",
                                            "LIVE_DISABLED"}


def test_the_limits_endpoint_lists_the_gates_and_the_limits(client):
    body = client.get("/execution/limits").json()["data"]
    assert body["gates"][0] == "DemoAccountValidator"
    assert body["gates"][-1] == "KillSwitch"
    assert body["limits"]["max_risk_per_trade"] <= 0.01


def test_the_propose_endpoint_refuses_under_the_shipped_defaults(client):
    response = client.post("/execution/demo/propose", json={
        "symbol": "EURUSD", "side": "BUY", "signal_id": "sig-1",
        "entry_price": 1.10, "stop_loss": 1.095})
    assert response.status_code == 200
    body = response.json()
    assert body["approved"] is False and body["executed"] is False
    assert body["live_trading_enabled"] is False
    assert body["environment"] == "DEMO"


def test_the_propose_endpoint_has_no_volume_field(client):
    """Section 8: a caller states the stop, never the lot size."""
    response = client.post("/execution/demo/propose", json={
        "symbol": "EURUSD", "side": "BUY", "signal_id": "sig-1",
        "entry_price": 1.10, "stop_loss": 1.095, "volume": 99.0})
    body = response.json()
    request = (body.get("request") or {})
    assert request.get("volume", 0) != 99.0


def test_the_propose_endpoint_refuses_an_order_it_cannot_size(client):
    """Without a stop and without a connected account there is no defined risk.

    On this host neither exists, so the refusal names whichever it hit first;
    what matters is that it refused rather than picking a lot size.
    """
    body = client.post("/execution/demo/propose", json={
        "symbol": "EURUSD", "side": "BUY", "signal_id": "sig-1",
        "entry_price": 1.10}).json()
    assert body["approved"] is False and body["executed"] is False
    assert set(body["reasons"]) & {"NO_STOP_DISTANCE", "NO_EQUITY"}
    assert body["sizing"]["volume"] == 0.0


def test_the_propose_endpoint_validates_the_side(client):
    assert client.post("/execution/demo/propose", json={
        "symbol": "EURUSD", "side": "SIDEWAYS", "signal_id": "s",
        "entry_price": 1.10, "stop_loss": 1.09}).status_code == 422


def test_the_propose_endpoint_validates_the_signal_id(client):
    assert client.post("/execution/demo/propose", json={
        "symbol": "EURUSD", "side": "BUY", "signal_id": "",
        "entry_price": 1.10, "stop_loss": 1.09}).status_code == 422


def test_approving_an_unknown_proposal_conflicts(client):
    response = client.post("/execution/proposals/nope/approve",
                           json={"approved_by": "Phu", "reason": "verified demo account"})
    assert response.status_code == 409
    assert response.json()["detail"] == "PROPOSAL_NOT_FOUND"


def test_an_approval_requires_a_named_human(client):
    assert client.post("/execution/proposals/nope/approve",
                       json={"approved_by": "P", "reason": "verified"}).status_code == 422


def test_the_daily_risk_endpoint_reports_its_timezone(client):
    body = client.get("/execution/daily-risk").json()["data"]
    assert body["timezone"] == "UTC"
    assert body["limits"]["max_daily_loss"] <= 0.03


def test_the_positions_endpoint_starts_empty(client):
    body = client.get("/execution/positions").json()["data"]
    assert body["count"] == 0 and body["summary"]["count"] == 0


def test_the_journal_and_comparison_endpoints_report_no_evidence(client):
    journal = client.get("/execution/journal").json()
    assert journal["data"]["count"] == 0 and journal["data_quality"] == "UNAVAILABLE"
    comparison = client.get("/execution/comparison").json()["data"]
    assert comparison["summary"]["samples"] == 0
    assert comparison["summary"]["reliable"] is False


def test_the_emergency_endpoint_never_reports_closed_positions(client):
    body = client.get("/execution/emergency").json()["data"]
    assert body["positions_closed"] is False


def test_the_demo_execution_dashboard_reports_a_blocked_posture(client):
    body = client.get("/dashboard/demo-execution").json()["data"]
    assert body["execution_mode"] == "OBSERVATION"
    assert body["execution_state"] == "EXECUTION_BLOCKED"
    assert body["live_trading_enabled"] is False
    assert body["real_account_execution"] is False
    assert {"DEMO_TRADING_DISABLED", "MT5_EXECUTION_DISABLED",
            "KILL_SWITCH_ENGAGED"} <= set(body["blocked_by"])
    assert body["kill_switch"]["engaged"] is True


def test_the_demo_execution_dashboard_carries_the_section_26_fields(client):
    body = client.get("/dashboard/demo-execution").json()["data"]
    for name in ("environment", "execution_mode", "kill_switch", "account", "daily_risk",
                 "open_positions", "position_summary", "pending_approvals", "performance",
                 "last_trade", "counters", "limits", "gates", "blocked_by"):
        assert name in body


def test_there_is_no_live_execution_route(client):
    """No endpoint anywhere accepts a live or real-account order."""
    for path in ("/execution/live", "/execution/real", "/execution/live/order",
                 "/execution/demo/live"):
        assert client.post(path, json={}).status_code == 404
