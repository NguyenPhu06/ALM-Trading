from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from api.schemas import TradingViewWebhook
from config.settings import get_settings, load_yaml
from data_quality import DataValidationError
from database.repositories import (
    CandleRepository,
    COTRepository,
    LiquidityEventRepository,
    StructureEventRepository,
    TradingViewAlertRepository,
)
from features.structure import MarketStructureEngine, StructureEventData
from features.regime.service import MarketRegimeService
from dataclasses import asdict
from database.session import check_connection, get_db
from logging_config import configure_logging


configure_logging()
logger = logging.getLogger(__name__)
app = FastAPI(title="ALM-Trading Market Data API", version="1A")


def pagination(limit: int, offset: int) -> tuple[int, int]:
    config = load_yaml().get("pagination", {})
    maximum = int(config.get("max_limit", 1000))
    return min(limit, maximum), offset


def as_dict(model: Any) -> dict[str, Any]:
    data = {column.name: getattr(model, column.name) for column in model.__table__.columns}
    if model.__table__.name == "structure_events":
        confirmation = data.get("confirmation_timestamp")
        data["confirmation_status"] = "CONFIRMED" if confirmation is None or confirmation <= data["event_timestamp"] else "PENDING"
    return data


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "phase": "1B"}


@app.get("/api/system/status")
def system_status() -> dict[str, Any]:
    settings = get_settings()
    yaml = load_yaml()
    return {
        "status": "ok",
        "database_connected": check_connection(),
        "live_trading_enabled": settings.live_trading_enabled,
        "paper_trading_enabled": bool(yaml.get("paper_trading", {}).get("enabled", True)),
        "tradingview_webhook_enabled": bool(yaml.get("tradingview", {}).get("webhook_enabled", True)),
        "cot_enabled": bool(yaml.get("cot", {}).get("enabled", True)),
    }


@app.post("/webhooks/tradingview", status_code=status.HTTP_200_OK)
async def tradingview_webhook(
    request: Request,
    x_tradingview_secret: str | None = Header(default=None, alias="X-TradingView-Secret"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    config = load_yaml().get("tradingview", {})
    if not config.get("webhook_enabled", True):
        raise HTTPException(status_code=503, detail="TradingView webhook disabled")
    try:
        raw_payload = await request.json()
        if not isinstance(raw_payload, dict):
            raise ValueError("payload must be a JSON object")
    except Exception:
        logger.warning("webhook validation failure: malformed JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

    expected = get_settings().tradingview_webhook_secret
    supplied = x_tradingview_secret
    if supplied is None and config.get("allow_payload_secret", True):
        supplied = raw_payload.get("secret")
    if not supplied or not hmac.compare_digest(str(supplied), expected):
        logger.warning("webhook validation failure: authentication rejected")
        raise HTTPException(status_code=401, detail="Invalid webhook authentication")

    try:
        payload = TradingViewWebhook.model_validate(raw_payload)
    except (ValidationError, DataValidationError) as exc:
        logger.warning("webhook validation failure: %s", exc)
        raise HTTPException(status_code=422, detail="Invalid webhook payload") from None

    audit_payload = dict(raw_payload)
    audit_payload.pop("secret", None)
    alert = TradingViewAlertRepository(db).add({
        "received_at": datetime.now(timezone.utc),
        "event_timestamp": payload.event_timestamp,
        "symbol": payload.symbol,
        "timeframe": payload.timeframe,
        "event_type": payload.event_type,
        "direction": payload.direction,
        "price": payload.price,
        "payload_json": audit_payload,
        "source": "tradingview",
    })
    logger.info("webhook received: alert_id=%d symbol=%s event=%s", alert.id, alert.symbol, alert.event_type)
    return {"status": "accepted", "id": alert.id}


@app.get("/api/candles")
def list_candles(
    symbol: str | None = None,
    timeframe: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    limit, offset = pagination(limit, offset)
    rows = CandleRepository(db).list(symbol=symbol.upper() if symbol else None, timeframe=timeframe.upper() if timeframe else None, offset=offset, limit=limit)
    return {"offset": offset, "limit": limit, "items": [as_dict(row) for row in rows]}


@app.get("/api/structure")
def list_structure(
    symbol: str | None = None,
    timeframe: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    limit, offset = pagination(limit, offset)
    rows = StructureEventRepository(db).list(
        symbol=symbol.upper() if symbol else None,
        timeframe=timeframe.upper() if timeframe else None,
        start=start, end=end, offset=offset, limit=limit,
    )
    return {"offset": offset, "limit": limit, "items": [as_dict(row) for row in rows]}


@app.get("/api/liquidity")
def list_liquidity(
    symbol: str | None = None,
    timeframe: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    limit, offset = pagination(limit, offset)
    rows = LiquidityEventRepository(db).list(
        symbol=symbol.upper() if symbol else None,
        timeframe=timeframe.upper() if timeframe else None,
        start=start, end=end, offset=offset, limit=limit,
    )
    return {"offset": offset, "limit": limit, "items": [as_dict(row) for row in rows]}


@app.get("/api/structure/bias")
def structure_bias(
    symbol: str | None = None,
    timeframe: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    limit, offset = pagination(limit, offset)
    rows = StructureEventRepository(db).list(
        symbol=symbol.upper() if symbol else None,
        timeframe=timeframe.upper() if timeframe else None,
        start=start, end=end, offset=offset, limit=limit,
    )
    events = [StructureEventData(
        row.event_timestamp, row.symbol, row.timeframe, row.event_type,
        row.direction, row.price or 0, row.confirmation_timestamp, row.strength,
        row.metadata_json or {},
    ) for row in reversed(rows)]
    bias, score = MarketStructureEngine.bias(events)
    return {"offset": offset, "limit": limit, "bias": bias.value, "score": score, "events_considered": len(events)}


@app.get("/api/regime")
def market_regime(
    symbol: str = "EURUSD",
    as_of: datetime | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return asdict(MarketRegimeService(db).calculate(symbol, as_of=as_of))


@app.get("/api/cot")
def list_cot(
    market: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    limit, offset = pagination(limit, offset)
    rows = COTRepository(db).list(market=market, offset=offset, limit=limit)
    return {"offset": offset, "limit": limit, "items": [as_dict(row) for row in rows]}


@app.get("/api/tradingview/alerts")
def list_alerts(
    symbol: str | None = None,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    limit, offset = pagination(limit, offset)
    rows = TradingViewAlertRepository(db).list(symbol=symbol.upper() if symbol else None, offset=offset, limit=limit)
    return {"offset": offset, "limit": limit, "items": [as_dict(row) for row in rows]}
