from __future__ import annotations

from config.settings import get_settings


PAYLOAD = {
    "symbol": "EURUSD", "timeframe": "15", "event": "LIQUIDITY_SWEEP",
    "direction": "BULLISH", "price": 1.1652, "timestamp": "2026-08-24T10:00:00Z",
}


def test_health_and_paginated_endpoints(client):
    health = client.get("/health")
    assert health.status_code == 200 and health.json()["status"] == "ok"
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

