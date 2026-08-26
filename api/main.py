from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import select

from api.schemas import TradingViewWebhook
from config.settings import get_settings, load_yaml
from data_quality import DataValidationError
from data_sources.health import MarketDataHealthService
from database.repositories import (
    CandleRepository,
    COTRepository,
    LiquidityEventRepository,
    StructureEventRepository,
    StrategyRepository,
    AlertRepository,
    TradingViewAlertRepository,
)
from features.structure import MarketStructureEngine, StructureEventData
from features.regime.service import MarketRegimeService
from features.intelligence import MarketIntelligenceEngine, MarketIntelligenceService
from dataclasses import asdict
from decimal import Decimal
from database.session import check_connection, get_db
from database.models import EconomicCalendarEventRecord, ExecutionResultRecord
from data_sources.gateway import DatabaseMarketDataProvider
from data_sources.snapshot import RealMarketSnapshotEngine
from data_sources.validators import MarketQualityValidator
from data_sources.providers.context import EconomicCalendarProvider, InstitutionalPositionProvider
from data_sources.providers.gateway import TradingViewAdapter
from data_sources.providers.factory import create_provider
from paper import PaperServiceState, PaperTradingService, calculate_performance, grouped_performance
from paper.service import bound_repository
from database.repositories import PaperTradingRepository
from database.session import SessionLocal
from orchestration.runner import OrchestrationRunner
from database.repositories.mt5 import MT5Repository
from execution.mt5.client import MT5ReadOnlyClient
from execution.mt5.service import MT5ReadOnlyService
from execution.mt5.execution_client import MT5ExecutionClient
from execution.mt5.execution_guard import ExecutionGuard
from execution.mt5.execution_service import DemoExecutionService
from execution.mt5.kill_switch import ExecutionKillSwitch
from execution.mt5.order_request import ExecutionIntent, OrderRequest, OrderSide, OrderType
from database.repositories.execution import ExecutionRepository
from pydantic import BaseModel, Field as PydanticField
from contextlib import asynccontextmanager
from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter
from monitoring.dashboard import DEFAULT_MAX_AGE_SECONDS, alignment as dashboard_alignment, envelope as _dashboard_envelope, unavailable_mtf
from database.models import PredictionRecord
from logging_config import configure_logging


configure_logging()
logger = logging.getLogger(__name__)
paper_service = PaperTradingService()
orchestration = OrchestrationRunner(SessionLocal, paper_service)
# MT5 is a DATA PROVIDER in Phase 10. The client holds connection state, so it is a
# singleton; the service is built per request because it needs the request session.
mt5_client = MT5ReadOnlyClient()


def mt5_service(db: Session) -> MT5ReadOnlyService:
    return MT5ReadOnlyService(db, client=mt5_client)


# Phase 11: DEMO execution. The kill switch is process-wide so that engaging it
# from one request blocks every subsequent one; it ships engaged.
execution_kill_switch = ExecutionKillSwitch(
    engaged=bool(get_settings().execution_kill_switch), reason="CONFIG_DEFAULT")
execution_guard = ExecutionGuard(get_settings(), kill_switch=execution_kill_switch)
mt5_execution_client = MT5ExecutionClient(
    get_settings(), connection=mt5_client.connection, read_client=mt5_client)


def demo_execution_service(db: Session) -> DemoExecutionService:
    return DemoExecutionService(
        db, guard=execution_guard, client=mt5_execution_client, read_client=mt5_client,
        repository=ExecutionRepository(db), alerts=alert_router(db),
    )


class DemoOrderPayload(BaseModel):
    """Manual DEMO test order. Deliberately minimal: no strategy can post here."""

    symbol: str
    side: str
    volume: float = PydanticField(gt=0)
    price: float | None = None
    sl: float | None = None
    tp: float | None = None
    comment: str = "ALM-DEMO-MANUAL"


class KillSwitchPayload(BaseModel):
    reason: str = PydanticField(min_length=3, max_length=255)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Restore persisted paper state, then start the loop only if it is enabled.

    The loop is opt-in (phase_9.orchestration.enabled). Starting the API must not
    start trading activity on its own, even paper activity.
    """
    session = SessionLocal()
    try:
        paper_service.restore(PaperTradingRepository(session))
        logger.info("restored paper state: positions=%d journals=%d",
                    len(paper_service.positions), len(paper_service.journals))
    except Exception:
        logger.exception("paper state restore failed; continuing with an empty book")
    finally:
        session.close()
    thread = orchestration.start_background()
    try:
        yield
    finally:
        if thread is not None:
            orchestration.stop()


app = FastAPI(title="ALM-Trading Paper Research API", version="9.0", lifespan=lifespan)
DASHBOARD_MAX_AGE_SECONDS = float(load_yaml().get("phase_9", {}).get("dashboard_max_age_seconds", DEFAULT_MAX_AGE_SECONDS))


def dashboard_envelope(data: Any, **kwargs: Any) -> dict[str, Any]:
    """Apply the configured dashboard freshness budget to every observation payload."""
    kwargs.setdefault("max_age_seconds", DASHBOARD_MAX_AGE_SECONDS)
    return _dashboard_envelope(data, **kwargs)


def _newest(*timestamps: Any) -> Any:
    """Freshness of a collection is the newest record it contains."""
    known = [t for t in timestamps if t is not None]
    return max(known) if known else None


def alert_engine(db: Session) -> AlertEngine:
    """Alerts have one store. Emission and /dashboard/alerts both go through the database."""
    return AlertEngine(AlertRepositoryNotificationProvider(AlertRepository(db)))


def alert_router(db: Session) -> AlertRouter:
    return AlertRouter(alert_engine(db))


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
    return {"status": "ok", "phase": "9"}


def _dashboard_intelligence(symbol:str,db:Session):
    try:
        snap=MarketIntelligenceService(db).calculate(symbol.upper());return snap, "VALID" if any(s.available for s in snap.timeframes.values()) else "UNAVAILABLE"
    except (ValueError,DataValidationError):return None,"UNAVAILABLE"

@app.get("/dashboard/overview")
def dashboard_overview(db:Session=Depends(get_db))->dict[str,Any]:
    providers=gateway_provider_status(db)["items"];market="ONLINE" if any(p["status"]=="ONLINE" for p in providers) else "DEGRADED" if any(p["status"]=="DEGRADED" for p in providers) else "OFFLINE"
    data={"environment":"PAPER","symbols":load_yaml().get("market_data",{}).get("symbols",[]),"timeframes":["D1","H4","H1","M30","M15","M5"],"system":{"database":"ONLINE" if check_connection() else "OFFLINE","market_data":market,"ai_model":"ONLINE" if StrategyRepository(db).latest_prediction() else "OFFLINE","strategy":"ONLINE" if StrategyRepository(db).latest_decision() else "DEGRADED","paper_engine":"ONLINE" if paper_service.state.value in {"RUNNING","PAUSED"} else "DEGRADED","api":"ONLINE","orchestration":"ONLINE" if orchestration.enabled else "DISABLED"},"risk_state":"BLOCKED" if market!="ONLINE" else "NORMAL","unread_alerts":len(AlertRepository(db).list(unread=True))}
    return dashboard_envelope(data,quality="VALID" if market=="ONLINE" else "WARNING",timestamp=datetime.now(timezone.utc))

@app.get("/dashboard/market/{symbol}")
def dashboard_market(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    market=RealMarketSnapshotEngine(DatabaseMarketDataProvider(db)).build(symbol.upper());return dashboard_envelope(asdict(market),source="market_gateway",quality="VALID" if market.strategy_allowed else "INVALID",timestamp=market.timestamp)

@app.get("/dashboard/mtf/{symbol}")
def dashboard_mtf(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    snap,quality=_dashboard_intelligence(symbol,db);states=unavailable_mtf() if snap is None else {tf:{"trend":s.trend,"structure":s.structure,"bos":s.bos,"choch":s.choch,"swing_high":s.swing_high,"swing_low":s.swing_low,"hh_hl_lh_ll":s.structure} for tf,s in snap.timeframes.items() if tf in {"D1","H4","H1","M30","M15","M5"}};return dashboard_envelope({"symbol":symbol.upper(),"timeframes":states,"alignment":dashboard_alignment(states)},source="market_intelligence",quality=quality,timestamp=snap.timestamp if snap else None)

@app.get("/dashboard/liquidity/{symbol}")
def dashboard_liquidity(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    snap,quality=_dashboard_intelligence(symbol,db);items={} if snap is None else {tf:{"levels":s.liquidity,"latest_sweep":s.sweep or "NO_CONFIRMED_SWEEP"} for tf,s in snap.timeframes.items()};return dashboard_envelope({"symbol":symbol.upper(),"timeframes":items},source="liquidity_engine",quality=quality,timestamp=snap.timestamp if snap else None)

@app.get("/dashboard/indicators/{symbol}")
def dashboard_indicators(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    snap,quality=_dashboard_intelligence(symbol,db);items={} if snap is None else {tf:{"indicators":s.indicators,"volatility":s.volatility,"smc":{"fvg":s.fvg,"order_block_candidate":s.order_block,"displacement":s.displacement,"premium_discount":s.premium_discount}} for tf,s in snap.timeframes.items()};return dashboard_envelope({"symbol":symbol.upper(),"timeframes":items},source="feature_engine",quality=quality,timestamp=snap.timestamp if snap else None)

@app.get("/dashboard/ai/{symbol}")
def dashboard_ai(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    row=db.query(PredictionRecord).filter(PredictionRecord.symbol==symbol.upper()).order_by(PredictionRecord.timestamp.desc()).first();data={"symbol":symbol.upper(),"model_status":"OFFLINE","status_reason":"NO_NEW_TRADE_MODEL_UNAVAILABLE","prediction":None} if row is None else {"symbol":symbol.upper(),"model_status":"ONLINE","prediction":row.prediction_json,"model_version":row.model_version,"feature_version":row.feature_version};return dashboard_envelope(data,source="neural_inference",quality="UNAVAILABLE" if row is None else "VALID",timestamp=row.timestamp if row else None)

@app.get("/dashboard/strategy/{symbol}")
def dashboard_strategy(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    repo=StrategyRepository(db);setup=repo.latest_setup(symbol);decision=repo.latest_decision(symbol);data={"symbol":symbol.upper(),"decision":decision.decision_json if decision else {"decision":"WAIT","reason_codes":["WHY_WAIT:DATA_UNAVAILABLE"]},"setup":setup.setup_json if setup else None};return dashboard_envelope(data,source="strategy_engine",quality="VALID" if decision else "UNAVAILABLE",timestamp=decision.timestamp if decision else None)

@app.get("/dashboard/risk")
def dashboard_risk()->dict[str,Any]:return dashboard_envelope({"account":asdict(paper_service.account),"daily_pnl":paper_service.daily.daily_pnl,"daily_drawdown":paper_service.daily.daily_drawdown,"risk_state":"BLOCKED" if paper_service.daily.paused or paper_service.risk.kill_switch.enabled else "NORMAL","kill_switch":paper_service.risk.kill_switch.enabled,"limits":load_yaml().get("phase_8",{})},source="paper_risk",quality="VALID",timestamp=paper_service.account.updated_at)
@app.get("/dashboard/positions")
def dashboard_positions()->dict[str,Any]:
    positions=list(paper_service.positions.values())
    latest=_newest(*[p.updated_at for p in positions],*[e.timestamp for e in paper_service.dca_events])
    return dashboard_envelope({"items":[asdict(p) for p in positions],"dca_events":[asdict(e) for e in paper_service.dca_events]},source="paper_engine",quality="VALID" if latest else "UNAVAILABLE",timestamp=latest)
@app.get("/dashboard/performance")
def dashboard_performance()->dict[str,Any]:
    closed=[j for j in paper_service.journals if j.final_result]
    latest=_newest(*[j.timestamp for j in closed])
    return dashboard_envelope(paper_performance(),source="paper_performance",quality="VALID" if closed else "UNAVAILABLE",timestamp=latest)
@app.get("/dashboard/journal")
def dashboard_journal()->dict[str,Any]:
    latest=_newest(*[j.timestamp for j in paper_service.journals])
    return dashboard_envelope({"items":[asdict(j) for j in paper_service.journals]},source="trade_journal",quality="VALID" if paper_service.journals else "UNAVAILABLE",timestamp=latest)

@app.get("/dashboard/alerts")
def dashboard_alerts(symbol:str|None=None,alert_type:str|None=None,severity:str|None=None,unread:bool|None=None,db:Session=Depends(get_db))->dict[str,Any]:
    rows=AlertRepository(db).list(symbol=symbol,alert_type=alert_type,severity=severity,unread=unread);latest=_newest(*[r.timestamp for r in rows]);return dashboard_envelope({"items":[as_dict(r) for r in rows],"unread":sum(not r.read for r in rows),"critical":sum(r.severity=="CRITICAL" for r in rows)},source="alert_engine",quality="VALID" if rows else "UNAVAILABLE",timestamp=latest)

@app.get("/dashboard/timeline/{symbol}")
def dashboard_timeline(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    structure=StructureEventRepository(db).list(symbol=symbol.upper(),limit=50,offset=0);liquidity=LiquidityEventRepository(db).list(symbol=symbol.upper(),limit=50,offset=0);items=[{"timestamp":r.event_timestamp,"type":r.event_type,"source":"structure","details":as_dict(r)} for r in structure]+[{"timestamp":r.event_timestamp,"type":r.event_type,"source":"liquidity","details":as_dict(r)} for r in liquidity];items.sort(key=lambda x:x["timestamp"],reverse=True);return dashboard_envelope({"symbol":symbol.upper(),"items":items[:100]},source="event_timeline",quality="VALID" if items else "UNAVAILABLE",timestamp=items[0]["timestamp"] if items else None)


@app.get("/paper/account")
def paper_account()->dict[str,Any]:return asdict(paper_service.account)
@app.get("/paper/positions")
def paper_positions()->dict[str,Any]:return {"items":[asdict(p) for p in paper_service.positions.values()]}
@app.get("/paper/orders")
def paper_orders()->dict[str,Any]:return {"items":[asdict(o) for o in paper_service.orders]}
@app.get("/paper/trades")
def paper_trades()->dict[str,Any]:return {"items":[asdict(j) for j in paper_service.journals if j.final_result is not None]}
@app.get("/paper/equity")
def paper_equity()->dict[str,Any]:return {"items":paper_service.equity_curve}
@app.get("/paper/performance")
def paper_performance()->dict[str,Any]:
    rows=[{**(j.final_result or {}),**j.market_context,"dca_depth":len(j.dca_history),"dca_mode":"WITH_DCA" if j.dca_history else "WITHOUT_DCA"} for j in paper_service.journals if j.final_result]
    return {"overall":asdict(calculate_performance(rows)),"by_direction":{k:asdict(v) for k,v in grouped_performance(rows,"direction").items()},"by_regime":{k:asdict(v) for k,v in grouped_performance(rows,"regime").items()},"by_session":{k:asdict(v) for k,v in grouped_performance(rows,"session").items()},"by_d1_bias":{k:asdict(v) for k,v in grouped_performance(rows,"d1_bias").items()},"by_dca":{k:asdict(v) for k,v in grouped_performance(rows,"dca_mode").items()}}
@app.get("/paper/risk")
def paper_risk()->dict[str,Any]:return {"service_state":paper_service.state,"kill_switch":paper_service.risk.kill_switch.enabled,"daily_pnl":paper_service.daily.daily_pnl,"daily_drawdown":paper_service.daily.daily_drawdown,"paper_trading_paused":paper_service.daily.paused,"live_trading_enabled":False}
@app.get("/paper/journal/latest")
def paper_journal_latest()->dict[str,Any]:
    if not paper_service.journals:raise HTTPException(status_code=404,detail="No paper journal found")
    return asdict(paper_service.journals[-1])
@app.get("/paper/dashboard")
def paper_dashboard(db:Session=Depends(get_db))->dict[str,Any]:return {"account":asdict(paper_service.account),"open_positions":len(paper_service.positions),"daily_pnl":paper_service.daily.daily_pnl,"drawdown":paper_service.account.max_drawdown,"latest_setup":None,"latest_prediction":None,"latest_strategy_decision":None,"risk_state":"PAUSED" if paper_service.daily.paused else "ACTIVE","provider_health":gateway_provider_status(db),"service_state":paper_service.state}
@app.post("/paper/start")
def paper_start()->dict[str,Any]:return {"state":paper_service.start(),"environment":"PAPER"}
@app.post("/paper/pause")
def paper_pause()->dict[str,Any]:return {"state":paper_service.pause(),"environment":"PAPER"}
@app.post("/paper/stop")
def paper_stop()->dict[str,Any]:return {"state":paper_service.stop(),"environment":"PAPER"}
@app.post("/paper/close-position/{position_id}")
def paper_close_position(position_id:str,price:float=Query(...,gt=0),db:Session=Depends(get_db))->dict[str,Any]:
    if position_id not in paper_service.positions:raise HTTPException(status_code=404,detail="Paper position not found")
    reason=("WHY_EXIT:MANUAL_PAPER_COMMAND",)
    with bound_repository(paper_service,PaperTradingRepository(db)):
        position=paper_service.close_position(position_id,price=price,timestamp=datetime.now(timezone.utc),reason=reason)
    alert_router(db).paper_exit(position,reason_codes=reason)
    return asdict(position)


# --------------------------------------------------------------- Phase 10: MT5
# Read-only. There is no order, close or modify endpoint, by design.

@app.get("/mt5/status")
def mt5_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    return dashboard_envelope(mt5_service(db).status(database_online=check_connection()),
                              source="mt5", quality="VALID",
                              timestamp=datetime.now(timezone.utc))


@app.get("/mt5/account")
def mt5_account(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = mt5_service(db).sync_account()
    if not result.ok:
        return dashboard_envelope({"account": None, "code": result.code, "reasons": list(result.reasons)},
                                  source="mt5", quality="UNAVAILABLE")
    account = result.data
    return dashboard_envelope({"account": account.as_public_dict(), "code": "OK"},
                              source="mt5", quality="VALID", timestamp=account.timestamp)


@app.get("/mt5/symbols")
def mt5_symbols(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = mt5_client.get_symbols()
    if not result.ok:
        return dashboard_envelope({"items": [], "code": result.code, "reasons": list(result.reasons)},
                                  source="mt5", quality="UNAVAILABLE")
    resolver = mt5_client.resolver
    items = []
    for canonical in mt5_client.canonical_symbols:
        info, code, candidates = resolver.try_resolve(canonical)
        items.append({"symbol": canonical, "broker_symbol": info.name if info else None,
                      "resolved": info is not None, "code": code or "OK",
                      "candidates": list(candidates)})
    return dashboard_envelope({"items": items, "broker_symbols": list(resolver.names()),
                               "code": "OK"}, source="mt5", quality="VALID",
                              timestamp=datetime.now(timezone.utc))


@app.get("/mt5/tick/{symbol}")
def mt5_tick(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = mt5_service(db).sync_tick(symbol)
    if not result.ok:
        return dashboard_envelope({"tick": None, "code": result.code, "reasons": list(result.reasons)},
                                  source="mt5", quality="UNAVAILABLE")
    tick = {key: (float(value) if isinstance(value, Decimal) else value)
            for key, value in result.data.items()}
    return dashboard_envelope({"tick": tick, "code": "OK"}, source="mt5", quality="VALID",
                              timestamp=tick["timestamp"])


@app.get("/mt5/candles/{symbol}/{timeframe}")
def mt5_candles(symbol: str, timeframe: str, count: int = Query(200, ge=1, le=5000),
                db: Session = Depends(get_db)) -> dict[str, Any]:
    result = mt5_client.get_rates(symbol, timeframe, count)
    if not result.ok:
        return dashboard_envelope({"items": [], "code": result.code, "reasons": list(result.reasons)},
                                  source="mt5", quality="UNAVAILABLE")
    gate = mt5_service(db).gate
    outcome = gate.evaluate_candles(result.data, symbol=symbol.upper(), timeframe=timeframe.upper())
    items = [{key: (float(value) if isinstance(value, Decimal) else value)
              for key, value in candle.items()} for candle in outcome.accepted]
    quality = "VALID" if outcome.valid else "INVALID"
    return dashboard_envelope(
        {"symbol": symbol.upper(), "timeframe": timeframe.upper(), "items": items,
         "count": len(items), "data_quality": str(outcome.status),
         "reasons": list(outcome.reasons), "source": "mt5", "code": outcome.code},
        source="mt5", quality=quality,
        timestamp=items[-1]["timestamp"] if items else None)


@app.get("/mt5/positions")
def mt5_positions(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = mt5_service(db).sync_positions()
    if not result.ok:
        return dashboard_envelope({"items": [], "code": result.code, "reasons": list(result.reasons)},
                                  source="mt5", quality="UNAVAILABLE")
    from execution.mt5.positions import PositionReader

    items = [position.as_dict() for position in result.data]
    return dashboard_envelope({"items": items, "summary": PositionReader.summarize(result.data),
                               "read_only": True, "code": "OK"},
                              source="mt5", quality="VALID" if items else "UNAVAILABLE",
                              timestamp=datetime.now(timezone.utc) if items else None)


@app.get("/mt5/orders")
def mt5_orders(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = mt5_service(db).sync_orders()
    if not result.ok:
        return dashboard_envelope({"items": [], "code": result.code, "reasons": list(result.reasons)},
                                  source="mt5", quality="UNAVAILABLE")
    items = [order.as_dict() for order in result.data]
    return dashboard_envelope({"items": items, "read_only": True, "code": "OK"},
                              source="mt5", quality="VALID" if items else "UNAVAILABLE",
                              timestamp=datetime.now(timezone.utc) if items else None)


@app.get("/mt5/health")
def mt5_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    report = mt5_client.health_check(database_online=check_connection())
    return dashboard_envelope(report.as_dict(), source="mt5", quality="VALID",
                              timestamp=report.timestamp)


@app.get("/mt5/data-quality")
def mt5_data_quality(limit: int = Query(100, ge=1, le=1000),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = MT5Repository(db).recent_quality_events(limit)
    items = [as_dict(row) for row in rows]
    return dashboard_envelope({"items": items, "count": len(items)}, source="mt5",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=rows[0].timestamp if rows else None)


@app.get("/mt5/snapshots")
def mt5_snapshots(limit: int = Query(50, ge=1, le=500),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = MT5Repository(db)
    account = repository.latest_account_snapshot()
    positions = repository.latest_positions(limit)
    connections = repository.recent_connection_events(limit)
    return dashboard_envelope({
        "account": as_dict(account) if account else None,
        "positions": [as_dict(row) for row in positions],
        "connections": [as_dict(row) for row in connections],
    }, source="mt5", quality="VALID" if account else "UNAVAILABLE",
        timestamp=account.timestamp if account else None)


@app.post("/mt5/connect")
def mt5_connect(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Opens a READ-ONLY session. There is no order route behind this endpoint."""
    report = mt5_service(db).connect()
    return {"state": str(report.state), "code": report.code, "reasons": list(report.reasons),
            "server": report.server, "login": report.masked_login,
            "read_only": True, "execution_enabled": False, "environment": get_settings().environment}


@app.post("/mt5/disconnect")
def mt5_disconnect(db: Session = Depends(get_db)) -> dict[str, Any]:
    report = mt5_service(db).disconnect()
    return {"state": str(report.state), "code": report.code, "read_only": True}


@app.get("/dashboard/mt5")
def dashboard_mt5(db: Session = Depends(get_db)) -> dict[str, Any]:
    """MT5 connection block for the Command Center. Never contains a credential."""
    service = mt5_service(db)
    status = service.status(database_online=check_connection())
    account = mt5_client.account
    positions = mt5_client.get_positions()
    return dashboard_envelope({
        **status,
        "balance": account.balance if account else None,
        "equity": account.equity if account else None,
        "free_margin": account.free_margin if account else None,
        "margin_level": account.margin_level if account else None,
        "currency": account.currency if account else None,
        "positions": len(positions.data) if positions.ok else 0,
    }, source="mt5", quality="VALID" if account else "UNAVAILABLE",
        timestamp=account.timestamp if account else None)


@app.get("/dashboard/mt5/mtf/{symbol}")
def dashboard_mt5_mtf(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """D1 -> M5 straight from MT5, each timeframe carrying its own age and source."""
    payload = mt5_service(db).multi_timeframe(symbol)
    available = [entry for entry in payload.values() if entry.get("available")]
    latest = max((entry["last_candle"] for entry in available), default=None)
    return dashboard_envelope({"symbol": symbol.upper(), "timeframes": payload, "source": "mt5"},
                              source="mt5", quality="VALID" if available else "UNAVAILABLE",
                              timestamp=latest)


# ------------------------------------------------- Phase 11: DEMO execution
# Manual test only. No strategy path posts here; see docs/execution_guard.md.

@app.get("/execution/status")
def execution_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    status = demo_execution_service(db).status()
    return dashboard_envelope(status, source="execution", quality="VALID",
                              timestamp=status["timestamp"])


@app.get("/execution/audit")
def execution_audit(request_id: str | None = None, limit: int = Query(100, ge=1, le=1000),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = ExecutionRepository(db)
    rows = repository.audit_trail(request_id) if request_id else repository.recent_audit(limit)
    items = [as_dict(row) for row in rows]
    return dashboard_envelope({"items": items, "count": len(items)}, source="execution",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=items[0]["timestamp"] if items else None)


@app.get("/execution/orders")
def execution_orders(limit: int = Query(50, ge=1, le=500),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = ExecutionRepository(db)
    latest = repository.latest_result()
    rows = (db.query(ExecutionResultRecord)
            .order_by(ExecutionResultRecord.timestamp.desc()).limit(limit).all())
    items = [as_dict(row) for row in rows]
    return dashboard_envelope({"items": items, "count": len(items)}, source="execution",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=latest.timestamp if latest else None)


@app.get("/execution/kill-switch")
def execution_kill_switch_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = ExecutionRepository(db)
    events = [as_dict(row) for row in repository.recent_kill_switch_events(20)]
    return dashboard_envelope({**execution_kill_switch.status(), "events": events},
                              source="execution", quality="VALID",
                              timestamp=execution_kill_switch.last_event.timestamp)


@app.post("/execution/kill-switch/engage")
def execution_kill_switch_engage(payload: KillSwitchPayload,
                                 db: Session = Depends(get_db)) -> dict[str, Any]:
    """Blocking execution is always allowed."""
    return demo_execution_service(db).engage_kill_switch(payload.reason, actor="api")


@app.post("/execution/kill-switch/release")
def execution_kill_switch_release(payload: KillSwitchPayload,
                                  db: Session = Depends(get_db)) -> dict[str, Any]:
    """Explicit, operator-initiated, and never automatic. A reason is mandatory."""
    return demo_execution_service(db).release_kill_switch(payload.reason, actor="api")


@app.post("/execution/demo/test")
def execution_demo_test(payload: DemoOrderPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Submit ONE manual DEMO order through ExecutionGuard.

    Every request is audited whether or not it is approved. The guard refuses
    unless DEMO_TRADING_ENABLED and MT5_EXECUTION_ENABLED are true, the kill
    switch is released, and the connected account is a verified DEMO account.
    """
    side = str(payload.side).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise HTTPException(status_code=422, detail="side must be BUY or SELL")
    order = OrderRequest(
        symbol=str(payload.symbol).strip().upper(), side=OrderSide(side), volume=payload.volume,
        order_type=OrderType.MARKET, price=payload.price, sl=payload.sl, tp=payload.tp,
        comment=payload.comment, intent=ExecutionIntent.MANUAL_TEST,
        magic_number=get_settings().mt5_magic_number,
    )
    logger.info("manual DEMO execution requested: %s %s %s request_id=%s",
                order.side, order.volume, order.symbol, order.request_id)
    outcome = demo_execution_service(db).execute(order)
    return {
        "request_id": order.request_id,
        "approved": outcome.decision.approved,
        "executed": outcome.executed,
        "environment": get_settings().environment,
        "automated_trading": False,
        "decision": outcome.decision.as_dict(),
        "result": outcome.result.as_dict(),
        "reconciliation": outcome.reconciliation.as_dict() if outcome.reconciliation else None,
    }


@app.get("/dashboard/execution")
def dashboard_execution(db: Session = Depends(get_db)) -> dict[str, Any]:
    service = demo_execution_service(db)
    status = service.status()
    positions = mt5_client.get_positions()
    account = mt5_client.account
    return dashboard_envelope({
        **status,
        "demo_account": {
            "broker": account.broker if account else get_settings().mt5_broker,
            "environment": account.environment if account else get_settings().environment,
            "server": account.server if account else get_settings().mt5_server,
            "login": account.masked_login if account else None,
            "balance": account.balance if account else None,
            "equity": account.equity if account else None,
        },
        "open_positions": [position.as_dict() for position in positions.data] if positions.ok else [],
    }, source="execution", quality="VALID", timestamp=status["timestamp"])


@app.get("/market/latest/{symbol}")
def gateway_latest(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    quote = DatabaseMarketDataProvider(db).get_latest_quote(symbol.upper())
    if quote is None: raise HTTPException(status_code=404, detail="No real market quote found")
    return quote


@app.get("/market/candles/{symbol}/{timeframe}")
def gateway_candles(symbol: str, timeframe: str, limit: int=Query(100,ge=1,le=1000), db: Session=Depends(get_db)) -> dict[str,Any]:
    rows=DatabaseMarketDataProvider(db).get_candles(symbol.upper(),timeframe.upper(),limit=limit)
    return {"symbol":symbol.upper(),"timeframe":timeframe.upper(),"candle_policy":"CLOSED_CANDLE_ONLY","items":rows}


@app.get("/market/providers/status")
def gateway_provider_status(db:Session=Depends(get_db))->dict[str,Any]:
    database=DatabaseMarketDataProvider(db).health_check(); tradingview=TradingViewAdapter().health_check(); configured=create_provider().health_check()
    def item(value):
        data=asdict(value);data["status"]="ONLINE" if data["status"]=="HEALTHY" else "OFFLINE" if data["status"] in {"ERROR","UNCONFIGURED"} else data["status"];return data
    return {"items":[item(database),item(configured),item(tradingview)]}


@app.get("/market/data-quality/{symbol}")
def gateway_quality(symbol:str,timeframe:str="M15",db:Session=Depends(get_db))->dict[str,Any]:
    provider=DatabaseMarketDataProvider(db);rows=provider.get_candles(symbol.upper(),timeframe.upper(),limit=500)
    return asdict(MarketQualityValidator().evaluate(rows,symbol=symbol.upper(),timeframe=timeframe.upper(),source=provider.name))


@app.get("/market/snapshot/{symbol}")
def gateway_snapshot(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    return asdict(RealMarketSnapshotEngine(DatabaseMarketDataProvider(db)).build(symbol.upper()))


@app.get("/market/cot/{asset}")
def gateway_cot(asset:str,db:Session=Depends(get_db))->dict[str,Any]:
    rows=COTRepository(db).list(market=asset,limit=100,offset=0)
    return {"asset":asset,"realtime":False,"latency_notice":"CFTC COT is delayed weekly public positioning data","items":[as_dict(row) for row in rows]}


@app.get("/market/calendar")
def gateway_calendar(start:datetime|None=None,end:datetime|None=None,db:Session=Depends(get_db))->dict[str,Any]:
    query=select(EconomicCalendarEventRecord)
    if start:query=query.where(EconomicCalendarEventRecord.scheduled_time>=start)
    if end:query=query.where(EconomicCalendarEventRecord.scheduled_time<=end)
    rows=list(db.scalars(query.order_by(EconomicCalendarEventRecord.scheduled_time).limit(500)))
    return {"provider_status":"AVAILABLE" if rows else "UNAVAILABLE","items":[as_dict(row) for row in rows]}


@app.get("/intelligence/snapshot/{symbol}")
def gateway_intelligence_snapshot(symbol:str,db:Session=Depends(get_db))->dict[str,Any]:
    market=RealMarketSnapshotEngine(DatabaseMarketDataProvider(db)).build(symbol.upper())
    intelligence=None
    if market.strategy_allowed:
        try:intelligence=MarketIntelligenceService(db)._jsonable(MarketIntelligenceService(db).calculate(symbol.upper(),as_of=market.timestamp))
        except (ValueError,DataValidationError):logger.warning("intelligence unavailable: symbol=%s timestamp=%s",symbol,market.timestamp)
    return {"timestamp":market.timestamp,"symbol":symbol.upper(),"market":asdict(market),"mtf_regime":intelligence.get("market_regime") if intelligence else None,"structure":intelligence.get("timeframes") if intelligence else None,"liquidity":intelligence.get("timeframes") if intelligence else None,"indicators":intelligence.get("timeframes") if intelligence else None,"neural_prediction":None,"cot_context":market.cot_context,"institutional_proxy":market.institutional_proxy,"data_quality":market.data_quality,"news_risk":market.news_risk,"strategy_state":"OBSERVE" if market.strategy_allowed else "BLOCKED","reasons":market.reasons}


def strategy_row(row: Any, field: str) -> dict[str, Any]:
    if row is None:
        raise HTTPException(status_code=404, detail="No Phase 6 research result found")
    return getattr(row, field)


@app.get("/strategy/setup/latest")
def latest_strategy_setup(symbol: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    return strategy_row(StrategyRepository(db).latest_setup(symbol), "setup_json")


@app.get("/strategy/snapshot/{symbol}")
def latest_strategy_snapshot(symbol: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return strategy_row(StrategyRepository(db).latest_snapshot(symbol), "snapshot_json")


@app.get("/strategy/decision/latest")
def latest_strategy_decision(symbol: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    return strategy_row(StrategyRepository(db).latest_decision(symbol), "decision_json")


@app.get("/strategy/backtest/latest")
def latest_strategy_backtest(db: Session = Depends(get_db)) -> dict[str, Any]:
    return strategy_row(StrategyRepository(db).latest_backtest(), "result_json")


@app.get("/strategy/performance")
def latest_strategy_performance(db: Session = Depends(get_db)) -> dict[str, Any]:
    result = strategy_row(StrategyRepository(db).latest_backtest(), "result_json")
    return result.get("performance", result)


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


@app.get("/api/market-data/candles")
def market_data_candles(
    symbol: str | None = None,
    timeframe: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    source: str | None = None,
    closed_only: bool = True,
    limit: int = Query(100, ge=1),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    limit, offset = pagination(limit, offset)
    rows = CandleRepository(db).list(
        symbol=symbol.upper() if symbol else None,
        timeframe=timeframe.upper() if timeframe else None,
        start=start, end=end, source=source, closed_only=closed_only,
        offset=offset, limit=limit,
    )
    return {"offset": offset, "limit": limit, "items": [as_dict(row) for row in rows]}


@app.get("/api/market-data/latest")
def market_data_latest(
    symbol: str = "EURUSD", timeframe: str = "M15", source: str | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    row = CandleRepository(db).latest(symbol.upper(), timeframe.upper(), source=source)
    if row is None:
        raise HTTPException(status_code=404, detail="No market data found")
    return as_dict(row)


@app.get("/api/market-data/health")
def market_data_health(
    symbol: str = "EURUSD", timeframe: str = "M15",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return MarketDataHealthService(db).health(symbol, timeframe)


@app.get("/api/market-data/gaps")
def market_data_gaps(
    symbol: str = "EURUSD", timeframe: str = "M15",
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    report = MarketDataHealthService(db).health(symbol, timeframe)
    return {"symbol": report["symbol"], "timeframe": report["timeframe"], "items": report["gap_details"]}


@app.get("/api/market-data/providers")
def market_data_providers(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"items": MarketDataHealthService(db).providers()}


@app.get("/api/market-data/readiness")
def market_data_readiness(db: Session = Depends(get_db)) -> dict[str, Any]:
    return MarketDataHealthService(db).readiness()


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


@app.get("/api/intelligence/{symbol}")
def market_intelligence(
    symbol: str, as_of: datetime | None = None, db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = MarketIntelligenceService(db)
    return service._jsonable(service.calculate(symbol, as_of=as_of))


@app.get("/api/intelligence/{symbol}/mtf")
def market_intelligence_mtf(
    symbol: str, as_of: datetime | None = None, db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = MarketIntelligenceService(db)
    return service._jsonable(service.calculate(symbol, as_of=as_of))


@app.get("/api/intelligence/{symbol}/{timeframe}")
def market_intelligence_timeframe(
    symbol: str, timeframe: str, as_of: datetime | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    timeframe = timeframe.upper()
    if timeframe not in MarketIntelligenceEngine.TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported intelligence timeframe")
    service = MarketIntelligenceService(db)
    return service._jsonable(service.calculate(symbol, as_of=as_of).timeframes[timeframe])


@app.get("/api/liquidity/{symbol}")
def current_liquidity(
    symbol: str, as_of: datetime | None = None, db: Session = Depends(get_db),
) -> dict[str, Any]:
    service = MarketIntelligenceService(db)
    snapshot = service.calculate(symbol, as_of=as_of)
    return {timeframe: {"liquidity": state.liquidity, "sweep": service._jsonable(state.sweep)} for timeframe, state in snapshot.timeframes.items()}


@app.get("/api/structure/{symbol}")
def current_structure(
    symbol: str, as_of: datetime | None = None, db: Session = Depends(get_db),
) -> dict[str, Any]:
    snapshot = MarketIntelligenceService(db).calculate(symbol, as_of=as_of)
    return {
        timeframe: {"trend": state.trend, "structure": state.structure, "bos": state.bos, "choch": state.choch,
                    "swing_high": state.swing_high, "swing_low": state.swing_low}
        for timeframe, state in snapshot.timeframes.items()
    }


@app.get("/api/indicators/{symbol}/{timeframe}")
def current_indicators(
    symbol: str, timeframe: str, as_of: datetime | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    timeframe = timeframe.upper()
    if timeframe not in MarketIntelligenceEngine.TIMEFRAMES:
        raise HTTPException(status_code=422, detail="Unsupported indicator timeframe")
    return MarketIntelligenceService(db).calculate(symbol, as_of=as_of).timeframes[timeframe].indicators


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
