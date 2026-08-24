from __future__ import annotations

import os

import httpx


def main() -> int:
    base_url = os.getenv("ALM_API_URL", "http://localhost:8000")
    secret = os.getenv("TRADINGVIEW_WEBHOOK_SECRET")
    if not secret:
        print("Webhook test failed: TRADINGVIEW_WEBHOOK_SECRET is not set")
        return 1
    payload = {
        "symbol": "EURUSD", "timeframe": "15", "event": "LIQUIDITY_SWEEP",
        "direction": "BULLISH", "price": 1.16520, "timestamp": "2026-08-24T10:00:00Z",
    }
    try:
        response = httpx.post(
            f"{base_url}/webhooks/tradingview", json=payload,
            headers={"X-TradingView-Secret": secret}, timeout=10,
        )
        response.raise_for_status()
        alert_id = response.json()["id"]
        lookup = httpx.get(f"{base_url}/api/tradingview/alerts", params={"limit": 100}, timeout=10)
        lookup.raise_for_status()
        found = any(row["id"] == alert_id for row in lookup.json()["items"])
        if not found:
            raise RuntimeError("HTTP 200 returned but database record was not found through the API")
        print(f"TradingView webhook PASS: HTTP 200, database alert id={alert_id}")
        return 0
    except Exception as exc:
        print(f"TradingView webhook FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

