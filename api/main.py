from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import select

from api.schemas import TradingViewWebhook
from config.settings import get_settings, load_yaml
from ai.edge.edge_detector import REQUIRED_BASELINES as EDGE_REQUIRED_BASELINES
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
from database.repositories.demo import DemoTradingRepository
from execution.demo import (
    ControlledDemoTradingService, DailyRiskTracker, DemoOrderRequest, DemoRiskLimits,
    DemoTradeJournal, ExecutionComparator, ExecutionMode, ExecutionModeResolver,
    IdempotencyRegistry, ManualApprovalQueue, PaperDemoComparison, PositionMonitor,
)
from execution.demo.approval import ApprovalRefused
from execution.demo.gates import DemoGateChain
from database.repositories.validation import ValidationRepository
from validation import (
    CircuitBreaker, RecoveryChecklist, RecoveryRefused, ValidationService,
)
from database.repositories.observation import ObservationRepository
from database.repositories.learning import LearningRepository
from database.repositories.forward import ForwardObservationRepository
from database.repositories.research import ResearchRepository
from ai.model_registry import (
    ApprovalToken, ChampionChallengerComparator, ModelRecord, ModelRegistry, ModelState,
    ModelTask, PromotionRefused,
)
from ai.inference.multitask_engine import ConfidenceThresholds
from ai.training.retraining import RetrainingPolicy
from observation.cycle import ObservationCycle
from observation.demo_account import DemoAccountValidator
from observation.health import ComponentHealth, SystemHealthMonitor
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


# Phase 16: controlled DEMO trading. The queue, journal, monitor, day budget and
# idempotency registry are process-wide for the same reason the kill switch is —
# an approval granted in one request must be visible to the next one.
demo_gate_chain = DemoGateChain(get_settings(), guard=execution_guard)
demo_approvals = ManualApprovalQueue()
demo_journal = DemoTradeJournal()
demo_monitor = PositionMonitor()
demo_daily_risk = DailyRiskTracker()
demo_idempotency = IdempotencyRegistry()
demo_counters: dict[str, int] = {}
demo_mode_resolver = ExecutionModeResolver(get_settings())


# Phase 17. The breaker is process-wide for the same reason the kill switch is,
# and separate from it on purpose: releasing the switch must not be a way around
# the recovery checklist.
circuit_breaker = CircuitBreaker(get_settings(), kill_switch=execution_kill_switch)


def validation_service(db: Session) -> ValidationService:
    """Reads and reports. It holds no execution client and no transport."""
    return ValidationService(ValidationRepository(db), settings=get_settings(),
                             breaker=circuit_breaker, alerts=alert_router(db))


def controlled_demo_service(db: Session) -> ControlledDemoTradingService:
    """A per-request service over the process-wide Phase 16 state."""
    repository = ExecutionRepository(db)
    demo_idempotency.repository = repository
    return ControlledDemoTradingService(
        db, chain=demo_gate_chain, guard=execution_guard, client=mt5_execution_client,
        read_client=mt5_client, repository=repository,
        demo_repository=DemoTradingRepository(db), alerts=alert_router(db),
        approvals=demo_approvals, journal=demo_journal, monitor=demo_monitor,
        daily=demo_daily_risk, idempotency=demo_idempotency, counters=demo_counters,
        breaker=circuit_breaker, validation_repository=ValidationRepository(db),
    )


def observation_cycle(db: Session) -> ObservationCycle:
    """A fresh cycle per request; it holds no state between calls."""
    return ObservationCycle(db, client=mt5_client, alerts=alert_router(db),
                            repository=ObservationRepository(db))


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


class DemoProposalPayload(BaseModel):
    """A Phase 16 execution proposal.

    There is no `volume` field, deliberately: section 8 forbids an arbitrary lot
    size, so the volume is derived from equity, risk and the stop distance. A
    caller states the stop, not the size.
    """

    symbol: str
    side: str
    signal_id: str = PydanticField(min_length=1, max_length=128)
    entry_price: float = PydanticField(gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_percent: float | None = PydanticField(default=None, gt=0, le=1)
    strategy_id: str | None = None
    strategy_version: str | None = None
    model_version: str | None = None
    feature_version: str | None = None
    risk_snapshot_id: str | None = None
    reason: str = ""
    intent: str = "NEW_ENTRY"


class DemoApprovalPayload(BaseModel):
    """Section 4: an approval names a human and states a reason."""

    approved_by: str = PydanticField(min_length=2, max_length=128)
    reason: str = PydanticField(min_length=3, max_length=255)


class BreakerRecoveryPayload(BaseModel):
    """Section 23. All four checks are explicit; none of them is inferred."""

    health_check: bool = False
    risk_check: bool = False
    account_validation: bool = False
    approved_by: str = PydanticField(min_length=2, max_length=128)
    reason: str = PydanticField(min_length=3, max_length=255)


class DemoRejectionPayload(BaseModel):
    reason: str = PydanticField(min_length=3, max_length=255)
    actor: str = PydanticField(default="operator", min_length=2, max_length=128)


class ApprovalPayload(BaseModel):
    """Human approval is the only route to promotion (section 27)."""

    approved_by: str = PydanticField(min_length=2, max_length=128)
    reason: str = PydanticField(min_length=3, max_length=255)


class RetrainingPayload(BaseModel):
    reason: str = PydanticField(min_length=3, max_length=255)
    new_observations: int = PydanticField(default=0, ge=0)


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


# --------------------------------------- Phase 16: controlled DEMO trading
# OBSERVATION is the default mode and LIVE is impossible. Every endpoint below
# either reports state or moves one order through the gate chain; none of them
# can change the mode, and none of them bypasses ExecutionGuard.

@app.get("/execution/mode")
def execution_mode() -> dict[str, Any]:
    """The configured execution mode and what it permits."""
    decision = demo_mode_resolver.resolve()
    return dashboard_envelope({
        **decision.as_dict(),
        "default_mode": str(ExecutionMode.OBSERVATION),
        "available_modes": [str(mode) for mode in ExecutionMode],
        "blocking_reasons": list(demo_mode_resolver.blocking_reasons()),
    }, source="demo_execution", quality="VALID", timestamp=decision.timestamp)


@app.get("/execution/limits")
def execution_limits() -> dict[str, Any]:
    limits = DemoRiskLimits.from_config().as_dict()
    return dashboard_envelope({"limits": limits, "gates": list(demo_gate_chain.gate_names())},
                              source="demo_execution", quality="VALID",
                              timestamp=datetime.now(timezone.utc))


@app.post("/execution/demo/propose")
def execution_demo_propose(payload: DemoProposalPayload,
                           db: Session = Depends(get_db)) -> dict[str, Any]:
    """Size, gate and record one proposal. Sends nothing, in any mode.

    In DEMO_AUTOMATED the caller follows up with nothing: `submit` happens only
    through this endpoint when the mode says so, and the response reports where
    the request stopped.
    """
    side = str(payload.side).strip().upper()
    if side not in {"BUY", "SELL"}:
        raise HTTPException(status_code=422, detail="side must be BUY or SELL")
    intent = str(payload.intent).strip().upper()
    if intent not in {item.value for item in ExecutionIntent}:
        raise HTTPException(status_code=422, detail="unknown execution intent")

    service = controlled_demo_service(db)
    sizing = service.size(symbol=payload.symbol, entry_price=payload.entry_price,
                          stop_loss=payload.stop_loss, risk_percent=payload.risk_percent)
    if not sizing.valid:
        # No stop distance, no tick economics, or a risk budget too small for one
        # lot. Refusing is the point: a default lot size would be an unpriced risk.
        return {"approved": False, "executed": False, "state": "BLOCKED",
                "reasons": list(sizing.reasons), "sizing": sizing.as_dict(),
                "environment": get_settings().environment, "live_trading_enabled": False}

    request = DemoOrderRequest.build(
        symbol=payload.symbol, side=side, volume=sizing.volume, signal_id=payload.signal_id,
        trading_day=service.trading_day(), price=payload.entry_price,
        stop_loss=payload.stop_loss, take_profit=payload.take_profit,
        strategy_id=payload.strategy_id, strategy_version=payload.strategy_version,
        model_version=payload.model_version, feature_version=payload.feature_version,
        risk_snapshot_id=payload.risk_snapshot_id, reason=payload.reason,
        intent=ExecutionIntent(intent), magic_number=get_settings().mt5_magic_number,
        risk_percent=sizing.risk_percent, risk_amount=sizing.risk_amount,
        stop_distance=sizing.stop_distance)
    logger.info("demo execution proposed: %s %s %s request_id=%s mode=%s",
                request.side, request.volume, request.symbol, request.request_id,
                service.mode)
    outcome = service.submit(request)
    body = outcome.as_dict()
    body.update({"environment": get_settings().environment, "live_trading_enabled": False,
                 "sizing": sizing.as_dict(), "mode": str(service.mode)})
    return body


@app.get("/execution/proposals")
def execution_proposals(limit: int = Query(50, ge=1, le=500),
                        db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = DemoTradingRepository(db).recent_proposals(limit)
    items = [as_dict(row) for row in rows]
    pending = [proposal.as_dict() for proposal in demo_approvals.pending()]
    return dashboard_envelope({"items": items, "count": len(items), "pending": pending},
                              source="demo_execution",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=items[0]["timestamp"] if items else None)


@app.post("/execution/proposals/{proposal_id}/approve")
def execution_proposal_approve(proposal_id: str, payload: DemoApprovalPayload,
                               db: Session = Depends(get_db)) -> dict[str, Any]:
    """Human approval, then submission. The approver is named in the audit trail."""
    service = controlled_demo_service(db)
    try:
        outcome = service.approve(proposal_id, approved_by=payload.approved_by,
                                  reason=payload.reason)
    except ApprovalRefused as error:
        raise HTTPException(status_code=409, detail=error.code) from error
    body = outcome.as_dict()
    body.update({"approved_by": payload.approved_by,
                 "environment": get_settings().environment, "live_trading_enabled": False})
    return body


@app.post("/execution/proposals/{proposal_id}/reject")
def execution_proposal_reject(proposal_id: str, payload: DemoRejectionPayload,
                              db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        proposal = controlled_demo_service(db).reject(proposal_id, reason=payload.reason,
                                                      actor=payload.actor)
    except ApprovalRefused as error:
        raise HTTPException(status_code=409, detail=error.code) from error
    return proposal.as_dict()


@app.get("/execution/daily-risk")
def execution_daily_risk(db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = DemoTradingRepository(db)
    state = demo_daily_risk.state
    history = [as_dict(row) for row in repository.daily_risk_history(30)]
    payload = state.as_dict() if state else {"trading_day": None,
                                             "reasons": ["NO_TRADING_DAY_STARTED"]}
    return dashboard_envelope({**payload, "history": history,
                               "timezone": demo_daily_risk.timezone_name,
                               "reset_hour": demo_daily_risk.reset_hour,
                               "limits": demo_daily_risk.limits.as_dict()},
                              source="demo_risk",
                              quality="VALID" if state else "UNAVAILABLE",
                              timestamp=state.updated_at if state else None)


@app.get("/execution/positions")
def execution_positions() -> dict[str, Any]:
    snapshots = [snapshot.as_dict() for snapshot in demo_monitor.snapshots]
    return dashboard_envelope({"items": snapshots, "count": len(snapshots),
                               "summary": demo_monitor.summary()},
                              source="demo_execution",
                              quality="VALID" if snapshots else "UNAVAILABLE",
                              timestamp=snapshots[0]["timestamp"] if snapshots else None)


@app.get("/execution/journal")
def execution_journal(limit: int = Query(100, ge=1, le=1000), closed: bool | None = None,
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = DemoTradingRepository(db).recent_journal(limit, closed=closed)
    items = [as_dict(row) for row in rows]
    return dashboard_envelope({"items": items, "count": len(items)}, source="demo_execution",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=items[0]["timestamp"] if items else None)


@app.get("/execution/comparison")
def execution_comparison(limit: int = Query(100, ge=1, le=1000),
                         db: Session = Depends(get_db)) -> dict[str, Any]:
    """Paper vs DEMO (section 29) and the error attribution behind it (section 32)."""
    rows = DemoTradingRepository(db).recent_comparisons(limit)
    items = [as_dict(row) for row in rows]
    summary = ExecutionComparator.summarize([
        PaperDemoComparison(
            request_id=row.request_id, symbol=row.symbol, paper_entry=row.paper_entry,
            demo_entry=row.demo_entry, paper_exit=row.paper_exit, demo_exit=row.demo_exit,
            entry_difference=row.entry_difference, exit_difference=row.exit_difference,
            spread=row.spread, slippage=row.slippage, commission=row.commission,
            swap=row.swap, pnl_difference=row.pnl_difference,
            within_tolerance=row.within_tolerance) for row in rows])
    return dashboard_envelope({"items": items, "count": len(items), "summary": summary},
                              source="demo_execution",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=items[0]["timestamp"] if items else None)


@app.get("/execution/performance")
def execution_performance(db: Session = Depends(get_db)) -> dict[str, Any]:
    performance = controlled_demo_service(db).performance()
    return dashboard_envelope(performance, source="demo_execution",
                              quality="VALID" if performance["samples"] else "UNAVAILABLE",
                              timestamp=performance["timestamp"])


@app.get("/execution/emergency")
def execution_emergency(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Report the emergency events. Reading this never triggers a shutdown."""
    rows = DemoTradingRepository(db).recent_emergency_events(50)
    items = [as_dict(row) for row in rows]
    return dashboard_envelope({"items": items, "count": len(items),
                               "positions_closed": False}, source="demo_execution",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=items[0]["timestamp"] if items else None)


@app.get("/dashboard/demo-execution")
def dashboard_demo_execution(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Section 26: one panel with everything an operator needs before arming."""
    status = controlled_demo_service(db).status()
    return dashboard_envelope(status, source="demo_execution", quality="VALID",
                              timestamp=status["timestamp"])


# ------------------------- Phase 17: shadow trading and DEMO validation
# Everything here reads and reports. The single write is the circuit-breaker
# reset, which refuses without the full section 23 checklist. No endpoint arms a
# mode, opens a flag or enables automation.

@app.get("/validation/shadow")
def validation_shadow(limit: int = Query(200, ge=1, le=1000), executed: bool | None = None,
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    """Shadow signals. `orders_sent` is 0 on every row, by construction."""
    rows = ValidationRepository(db).recent_shadow_signals(limit, executed=executed)
    items = [as_dict(row) for row in rows]
    return dashboard_envelope({"items": items, "count": len(items), "orders_sent": 0},
                              source="validation",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=items[0]["timestamp"] if items else None)


@app.get("/validation/shadow/outcomes")
def validation_shadow_outcomes(limit: int = Query(500, ge=1, le=2000),
                               db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = ValidationRepository(db).recent_shadow_outcomes(limit)
    items = [as_dict(row) for row in rows]
    return dashboard_envelope({"items": items, "count": len(items)}, source="validation",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=items[0]["resolved_at"] if items else None)


@app.get("/validation/comparison")
def validation_comparison(limit: int = Query(200, ge=1, le=1000),
                          db: Session = Depends(get_db)) -> dict[str, Any]:
    """SHADOW vs DEMO, with the difference attributed rather than merely measured."""
    repository = ValidationRepository(db)
    items = [as_dict(row) for row in repository.recent_comparisons(limit)]
    summary = validation_service(db).comparison_summary(limit)
    return dashboard_envelope({"items": items, "count": len(items), "summary": summary},
                              source="validation",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=items[0]["timestamp"] if items else None)


@app.get("/validation/execution-quality")
def validation_execution_quality(db: Session = Depends(get_db)) -> dict[str, Any]:
    service = controlled_demo_service(db)
    rows = (db.query(ExecutionResultRecord)
            .order_by(ExecutionResultRecord.timestamp.desc()).limit(500).all())
    records = [{"status": row.status, "slippage": _slippage(row), "spread": None,
                "latency_ms": None} for row in rows]
    quality = validation_service(db).execution_quality(
        records,
        reconciliation_failures=service.counters.get("reconciliation_failures", 0),
        connection_failures=0)
    return dashboard_envelope(quality, source="validation",
                              quality="VALID" if quality["submitted"] else "UNAVAILABLE",
                              timestamp=quality["timestamp"])


def _slippage(row: Any) -> float | None:
    """Filled minus requested, when both are known. Never assumed to be zero."""
    if row.filled_price is None or row.requested_price is None:
        return None
    return abs(float(row.filled_price) - float(row.requested_price))


@app.get("/validation/signal-quality")
def validation_signal_quality(db: Session = Depends(get_db)) -> dict[str, Any]:
    quality = validation_service(db).signal_quality()
    return dashboard_envelope(quality, source="validation",
                              quality="VALID" if quality["signals"] else "UNAVAILABLE",
                              timestamp=datetime.now(timezone.utc))


@app.get("/validation/segments")
def validation_segments(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Regime, session and timeframe. A cell below its floor is not evidence."""
    segments = validation_service(db).segment_performance()
    return dashboard_envelope(segments, source="validation", quality="VALID",
                              timestamp=datetime.now(timezone.utc))


@app.get("/validation/windows")
def validation_windows(db: Session = Depends(get_db)) -> dict[str, Any]:
    windows = validation_service(db).rolling_windows()
    return dashboard_envelope(windows, source="validation", quality="VALID",
                              timestamp=datetime.now(timezone.utc))


@app.get("/validation/gates")
def validation_gates(window: str = Query("30d"),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    """A failing gate reports. It never enables higher-risk execution."""
    report = validation_service(db).performance_gates(window=window)
    return dashboard_envelope(report, source="validation", quality="VALID",
                              timestamp=report["timestamp"])


@app.get("/validation/eligibility")
def validation_eligibility(db: Session = Depends(get_db)) -> dict[str, Any]:
    """DEMO_AUTOMATION_ELIGIBLE. Computed, advisory, and never self-applying."""
    settings = get_settings()
    service = controlled_demo_service(db)
    eligibility = validation_service(db).automation_eligibility(
        kill_switch_engaged=service.kill_switch.engaged,
        reconciliation_failures=service.counters.get("reconciliation_failures", 0),
        circuit_breaker_open=circuit_breaker.open)
    return dashboard_envelope({
        **eligibility.as_dict(),
        "demo_automated_execution_enabled": settings.demo_automated_execution_enabled,
        "demo_automation_approved": settings.demo_automation_approved,
        "execution_mode": settings.execution_mode,
    }, source="validation", quality="VALID", timestamp=eligibility.timestamp)


@app.get("/validation/circuit-breaker")
def validation_circuit_breaker(db: Session = Depends(get_db)) -> dict[str, Any]:
    events = [as_dict(row) for row in ValidationRepository(db).recent_breaker_events(50)]
    status = circuit_breaker.status()
    return dashboard_envelope({**status, "history": events}, source="circuit_breaker",
                              quality="VALID", timestamp=status.get("since"))


@app.post("/validation/circuit-breaker/reset")
def validation_circuit_breaker_reset(payload: BreakerRecoveryPayload,
                                     db: Session = Depends(get_db)) -> dict[str, Any]:
    """Section 23. Health check, risk check, account validation and a named human.

    DEMO_AUTOMATED does not resume by itself: closing the breaker only removes
    this block, and every other gate is still evaluated per order.
    """
    checklist = RecoveryChecklist(
        health_check=payload.health_check, risk_check=payload.risk_check,
        account_validation=payload.account_validation, approved_by=payload.approved_by,
        reason=payload.reason)
    try:
        event = validation_service(db).reset_breaker(checklist, actor=payload.approved_by)
    except RecoveryRefused as error:
        raise HTTPException(status_code=409, detail={"code": "RECOVERY_INCOMPLETE",
                                                     "missing": list(error.missing)}) from error
    return {**event.as_dict(), "state": str(event.state),
            "demo_automated_resumed": False}


@app.get("/validation/review/daily")
def validation_daily_review(db: Session = Depends(get_db)) -> dict[str, Any]:
    service = controlled_demo_service(db)
    review = validation_service(db).daily_review(
        kill_switch="ENGAGED" if service.kill_switch.engaged else "RELEASED",
        execution_failures=service.counters.get("execution_errors", 0))
    return dashboard_envelope(review, source="validation", quality="VALID",
                              timestamp=review["generated_at"])


@app.get("/validation/review/weekly")
def validation_weekly_review(db: Session = Depends(get_db)) -> dict[str, Any]:
    review = validation_service(db).weekly_review()
    return dashboard_envelope(review, source="validation", quality="VALID",
                              timestamp=review["generated_at"])


@app.get("/dashboard/validation")
def dashboard_validation(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Section 24: shadow and DEMO side by side, plus the two stop mechanisms."""
    settings = get_settings()
    service = controlled_demo_service(db)
    validation = validation_service(db)
    shadow = validation.signal_quality()
    demo = service.performance()
    windows = validation.rolling_windows()
    comparison = validation.comparison_summary()
    quality = validation.execution_quality(
        [{"status": row.status, "slippage": _slippage(row)} for row in
         db.query(ExecutionResultRecord)
         .order_by(ExecutionResultRecord.timestamp.desc()).limit(500).all()],
        reconciliation_failures=service.counters.get("reconciliation_failures", 0))

    return dashboard_envelope({
        "system_mode": settings.execution_mode,
        "live_trading_enabled": False,
        "real_account_execution": False,
        "shadow_signals": shadow["signals"],
        "demo_trades": demo["samples"],
        "paper_trades": len(paper_service.journals),
        "shadow_win_rate": shadow["win_rate"],
        "demo_win_rate": demo["win_rate"],
        "shadow_expectancy": shadow["expectancy"],
        "demo_expectancy": demo["expectancy"],
        "shadow_pnl": shadow["net_pnl"],
        "demo_pnl": demo["net_pnl"],
        "shadow_demo_pnl_delta": _delta(demo["net_pnl"], shadow["net_pnl"]),
        "average_slippage": quality["average_slippage"],
        "execution_latency": quality["latency_ms"],
        "reconciliation_status": ("FAILED" if service.counters.get("reconciliation_failures")
                                  else "OK"),
        "current_champion": (service.journal.entries[-1].strategy_version
                             if service.journal.entries else None),
        "nn_confidence": None,
        "model_drift": None,
        "edge_status": windows.get("edge_status"),
        "circuit_breaker": circuit_breaker.status(),
        "kill_switch": service.kill_switch.status(),
        "comparison": comparison,
        "execution_quality": quality,
        "windows": windows.get("windows"),
        "shadow_orders_sent": 0,
        "timestamp": datetime.now(timezone.utc),
    }, source="validation", quality="VALID", timestamp=datetime.now(timezone.utc))


def _delta(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    return round(float(left) - float(right), 8)


# ------------------------------------------ Phase 12: observation & validation
# Observation mode: the system reads the live market, calculates every signal,
# and sends zero orders. The terminal stage is always a recorded simulation.

@app.get("/market/snapshot")
def market_snapshot(symbol: str = Query(None), refresh: bool = Query(False),
                    db: Session = Depends(get_db)) -> dict[str, Any]:
    """One coherent view of the market: price, regime, structure, NN, strategy, execution.

    `refresh=true` runs a live observation cycle; otherwise the most recent stored
    snapshot is returned so the dashboard does not re-run the pipeline on every poll.
    """
    settings = get_settings()
    target = (symbol or (settings.observation_symbol_list or ("EURUSD",))[0]).upper()
    repository = ObservationRepository(db)

    if refresh:
        result = observation_cycle(db).run(target)
        if result.market is not None:
            payload = result.market.as_dict()
            payload["observation_mode"] = settings.observation_mode
            payload["orders_sent"] = 0
            return dashboard_envelope(payload, source="observation", quality="VALID",
                                      timestamp=result.timestamp)
        return dashboard_envelope(
            {"symbol": target, "stage": result.stage, "halted": True,
             "reasons": list(result.reasons), "orders_sent": 0,
             "observation_mode": settings.observation_mode,
             "account": result.account.as_dict() if result.account else None},
            source="observation", quality="UNAVAILABLE", timestamp=result.timestamp)

    row = repository.latest_market_snapshot(target)
    if row is None:
        return dashboard_envelope({"symbol": target, "available": False,
                                   "hint": "call with refresh=true to run a cycle",
                                   "orders_sent": 0,
                                   "observation_mode": settings.observation_mode},
                                  source="observation", quality="UNAVAILABLE")
    payload = dict(row.snapshot_json or {})
    payload.update({"observation_mode": settings.observation_mode, "orders_sent": 0,
                    "cycle_id": row.cycle_id})
    return dashboard_envelope(payload, source="observation", quality="VALID",
                              timestamp=row.timestamp)


@app.get("/system/health")
def system_health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Per-component health: HEALTHY / DEGRADED / FAILED / UNKNOWN."""
    settings = get_settings()
    monitor = SystemHealthMonitor()

    database_ok = check_connection()
    account = DemoAccountValidator(settings).validate_client(mt5_client)
    mt5_report = mt5_client.health_check(database_online=database_ok)

    repository = ObservationRepository(db)
    latest_feature = repository.latest_feature_snapshot()
    latest_health = repository.latest_health()
    strategy_row = StrategyRepository(db).latest_decision()
    prediction_row = StrategyRepository(db).latest_prediction()

    reported = {
        "api": ComponentHealth.HEALTHY,
        "database": ComponentHealth.HEALTHY if database_ok else ComponentHealth.FAILED,
        "mt5": str(mt5_report.state),
        "market_data": ComponentHealth.HEALTHY if account.valid else ComponentHealth.UNKNOWN,
        "data_quality": ComponentHealth.HEALTHY if latest_feature else ComponentHealth.UNKNOWN,
        "strategy": ComponentHealth.HEALTHY if strategy_row else ComponentHealth.UNKNOWN,
        "nn": ComponentHealth.HEALTHY if prediction_row else ComponentHealth.UNKNOWN,
        "risk": ComponentHealth.HEALTHY if strategy_row else ComponentHealth.UNKNOWN,
        # Execution is intentionally disabled; that is healthy, not degraded.
        "execution": ComponentHealth.HEALTHY,
        "dashboard": ComponentHealth.HEALTHY,
        "monitoring": ComponentHealth.HEALTHY,
    }
    details = {
        "mt5": {"account_status": str(account.status), "server": account.as_dict()["account"]["server"]},
        "execution": {"observation_mode": settings.observation_mode,
                      "demo_trading_enabled": settings.demo_trading_enabled,
                      "mt5_execution_enabled": settings.mt5_execution_enabled,
                      "kill_switch": settings.execution_kill_switch,
                      "automated_trading": False},
    }
    health = monitor.build(reported, details=details,
                           last_error=latest_health.last_error if latest_health else None)
    return dashboard_envelope(health.as_dict(), source="observation", quality="VALID",
                              timestamp=health.timestamp)


@app.get("/observation/status")
def observation_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    repository = ObservationRepository(db)
    simulations = repository.recent_simulations(20)
    return dashboard_envelope({
        "observation_mode": settings.observation_mode,
        "symbols": list(settings.observation_symbol_list),
        "interval_seconds": settings.observation_interval_seconds,
        "automated_trading": False,
        "orders_sent": 0,
        "recent_simulations": [as_dict(row) for row in simulations],
    }, source="observation", quality="VALID" if simulations else "UNAVAILABLE",
        timestamp=simulations[0].timestamp if simulations else None)


@app.get("/observation/performance")
def observation_performance(limit: int = Query(100, ge=1, le=1000),
                            db: Session = Depends(get_db)) -> dict[str, Any]:
    """Forward observation data. This is NOT a backtest and NOT a realised result."""
    rows = ObservationRepository(db).recent_performance(limit)
    items = [as_dict(row) for row in rows]
    return dashboard_envelope({
        "items": items, "count": len(items), "orders_sent": 0,
        "note": "Hypothetical forward observation only; no order was ever placed.",
    }, source="observation", quality="VALID" if items else "UNAVAILABLE",
        timestamp=rows[0].opened_at if rows else None)


@app.post("/observation/cycle")
def observation_run_cycle(symbol: str = Query(None),
                          db: Session = Depends(get_db)) -> dict[str, Any]:
    """Run one observation cycle on demand. Sends nothing; records everything."""
    settings = get_settings()
    target = (symbol or (settings.observation_symbol_list or ("EURUSD",))[0]).upper()
    result = observation_cycle(db).run(target)
    return {**result.as_dict(), "observation_mode": settings.observation_mode,
            "automated_trading": False}


@app.get("/dashboard/observation")
def dashboard_observation(symbol: str = Query(None),
                          db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    target = (symbol or (settings.observation_symbol_list or ("EURUSD",))[0]).upper()
    repository = ObservationRepository(db)
    row = repository.latest_market_snapshot(target)
    account = DemoAccountValidator(settings).validate_client(mt5_client)
    snapshot = dict(row.snapshot_json or {}) if row else {}
    return dashboard_envelope({
        "symbol": target,
        "observation_mode": settings.observation_mode,
        "automated_trading": False,
        "orders_sent": 0,
        "account": account.as_dict(),
        "price": snapshot.get("price", {}),
        "spread": snapshot.get("spread", {}),
        "session": snapshot.get("sessions", {}),
        "regime": snapshot.get("regime", {}),
        "timeframes": snapshot.get("timeframes", {}),
        "structure": snapshot.get("structure", {}),
        "liquidity": snapshot.get("liquidity", {}),
        "indicators": snapshot.get("indicators", {}),
        "neural_network": snapshot.get("neural_network"),
        "strategy": snapshot.get("strategy", {}),
        "risk": snapshot.get("risk", {}),
        "execution": snapshot.get("execution", {}),
        "data_quality": snapshot.get("data_quality", {}),
        "last_error": (repository.latest_health().last_error
                       if repository.latest_health() else None),
    }, source="observation", quality="VALID" if row else "UNAVAILABLE",
        timestamp=row.timestamp if row else None)


# ------------------------------------------------------ Phase 13: AI learning
# Read-only reporting plus two human-gated writes. Training itself is an explicit
# job (scripts/train_forward_model.py); no endpoint fits a model.

def _model_rows_to_dicts(rows) -> list[dict[str, Any]]:
    return [as_dict(row) for row in rows]


@app.get("/ai/models")
def ai_models(limit: int = Query(50, ge=1, le=500),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = LearningRepository(db).recent_models(limit)
    items = _model_rows_to_dicts(rows)
    return dashboard_envelope({"items": items, "count": len(items)}, source="ai",
                              quality="VALID" if items else "UNAVAILABLE",
                              timestamp=rows[0].training_timestamp if rows else None)


@app.get("/ai/champion")
def ai_champion(task: str = Query("direction"), symbol: str = Query("EURUSD"),
                timeframe: str = Query("M5"), db: Session = Depends(get_db)) -> dict[str, Any]:
    key = ModelTask(task=task, symbol=symbol.upper(), timeframe=timeframe.upper()).key
    repository = LearningRepository(db)
    champion = repository.champion(key)
    challengers = repository.challengers(key)
    return dashboard_envelope({
        "task": key,
        "champion": as_dict(champion) if champion else None,
        "challengers": _model_rows_to_dicts(challengers),
        "challenger_count": len(challengers),
    }, source="ai", quality="VALID" if champion else "UNAVAILABLE",
        timestamp=champion.training_timestamp if champion else None)


@app.get("/ai/dataset")
def ai_dataset(db: Session = Depends(get_db)) -> dict[str, Any]:
    audit = LearningRepository(db).latest_dataset_audit()
    return dashboard_envelope({"audit": as_dict(audit) if audit else None,
                               "labelled_observations": LearningRepository(db).labelled_count()},
                              source="ai", quality="VALID" if audit else "UNAVAILABLE",
                              timestamp=audit.created_at if audit else None)


@app.get("/ai/drift")
def ai_drift(limit: int = Query(50, ge=1, le=500),
             db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = LearningRepository(db).recent_drift(limit)
    items = _model_rows_to_dicts(rows)
    return dashboard_envelope({
        "items": items, "count": len(items),
        "flagged": sum(1 for row in rows if row.flagged),
        # Constant: drift detection never triggers retraining or promotion.
        "action": "FLAG_ONLY",
    }, source="ai", quality="VALID" if items else "UNAVAILABLE",
        timestamp=rows[0].timestamp if rows else None)


@app.get("/ai/retraining")
def ai_retraining(limit: int = Query(50, ge=1, le=500),
                  db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = LearningRepository(db).recent_retraining_requests(limit)
    items = _model_rows_to_dicts(rows)
    return dashboard_envelope({"items": items, "count": len(items),
                               "auto_trains": False, "auto_promotes": False},
                              source="ai", quality="VALID" if items else "UNAVAILABLE",
                              timestamp=rows[0].created_at if rows else None)


@app.get("/ai/thresholds")
def ai_thresholds() -> dict[str, Any]:
    thresholds = ConfidenceThresholds.from_config()
    return dashboard_envelope({**thresholds.as_dict(),
                               "note": "validate thresholds out-of-sample before trusting them"},
                              source="ai", quality="VALID",
                              timestamp=datetime.now(timezone.utc))


@app.post("/ai/retraining/request")
def ai_request_retraining(payload: RetrainingPayload,
                          db: Session = Depends(get_db)) -> dict[str, Any]:
    """Records that retraining is warranted. Does NOT train and does NOT promote."""
    policy = RetrainingPolicy(get_settings())
    request = policy.evaluate(new_observations=payload.new_observations, manual=True)
    LearningRepository(db).save_retraining_request(request)
    logger.info("retraining requested: %s", payload.reason)
    return {**request.as_dict(), "reason": payload.reason,
            "note": "a request is not a training run; run scripts/train_forward_model.py"}


@app.post("/ai/models/{model_id}/approve")
def ai_approve_model(model_id: str, payload: ApprovalPayload,
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    """Human approval gate. Promotion happens only here, and only with a named approver."""
    repository = LearningRepository(db)
    row = repository.get_model(model_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown model")

    registry = ModelRegistry(repository=repository)
    record = _record_from_row(row)
    registry.register(record)
    incumbent = repository.champion(row.task_key)
    if incumbent is not None and incumbent.model_id != model_id:
        registry.register(_record_from_row(incumbent))

    try:
        if record.state is ModelState.EXPERIMENTAL:
            registry.transition(model_id, ModelState.VALIDATED, note="approved for validation")
        promoted = registry.promote(
            model_id, ApprovalToken(payload.approved_by, payload.reason),
            force=incumbent is None)
    except PromotionRefused as error:
        return {"model_id": model_id, "promoted": False, "reason": str(error),
                "comparison": registry.evaluate_promotion(model_id).as_dict()}

    return {"model_id": model_id, "promoted": True, "state": str(promoted.state),
            "approved_by": payload.approved_by,
            "comparison": registry.evaluate_promotion(model_id).as_dict()}


def _record_from_row(row) -> ModelRecord:
    payload = dict(row.record_json or {})
    task = payload.get("task") or {}
    return ModelRecord(
        model_id=row.model_id, model_version=row.model_version,
        task=ModelTask(task.get("task", row.task), task.get("symbol", row.symbol),
                       task.get("timeframe", row.timeframe)),
        feature_version=row.feature_version, label_version=row.label_version,
        training_dataset_version=row.training_dataset_version,
        preprocessing_version=row.preprocessing_version,
        state=ModelState(row.state), training_timestamp=row.training_timestamp,
        validation_metrics=payload.get("validation_metrics", {}),
        test_metrics=payload.get("test_metrics", {}),
        walk_forward_metrics=payload.get("walk_forward_metrics", {}),
        regime_metrics=payload.get("regime_metrics", {}),
        session_metrics=payload.get("session_metrics", {}),
        baseline_comparison=payload.get("baseline_comparison", {}),
        calibration=payload.get("calibration", {}),
        explainability=payload.get("explainability", {}),
        edge_verdict=row.edge_verdict, artifact_path=row.artifact_path)


@app.get("/dashboard/ai")
def dashboard_ai(task: str = Query("direction"), symbol: str = Query("EURUSD"),
                 timeframe: str = Query("M5"), db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = LearningRepository(db)
    key = ModelTask(task=task, symbol=symbol.upper(), timeframe=timeframe.upper()).key
    champion = repository.champion(key)
    challengers = repository.challengers(key)
    audit = repository.latest_dataset_audit()
    drift = repository.recent_drift(20)
    payload = dict(champion.record_json or {}) if champion else {}
    test_metrics = payload.get("test_metrics", {})
    walk_forward = payload.get("walk_forward_metrics", {})
    prediction = StrategyRepository(db).latest_prediction()

    return dashboard_envelope({
        "task": key,
        "current_model": champion.model_id if champion else None,
        "model_version": champion.model_version if champion else None,
        "feature_version": champion.feature_version if champion else None,
        "model_status": champion.state if champion else "NONE",
        "champion": as_dict(champion) if champion else None,
        "challenger": as_dict(challengers[0]) if challengers else None,
        "challenger_count": len(challengers),
        "edge": champion.edge_verdict if champion else "NO_EDGE",
        "nn": (prediction.prediction_json if prediction else None),
        "expected_return": test_metrics.get("expectancy"),
        "expected_mfe": test_metrics.get("mfe"),
        "expected_mae": test_metrics.get("mae"),
        "walk_forward_score": walk_forward.get("mean_accuracy"),
        "walk_forward_stability": walk_forward.get("stability"),
        "dataset_size": audit.row_count if audit else 0,
        "dataset_id": audit.dataset_id if audit else None,
        "last_training": champion.training_timestamp if champion else None,
        "last_validation": payload.get("validation_metrics", {}).get("samples"),
        "drift_flagged": sum(1 for row in drift if row.flagged),
        "drift_action": "FLAG_ONLY",
        "explainability": payload.get("explainability", {}).get("groups", [])[:5],
        "thresholds": ConfidenceThresholds.from_config().as_dict(),
        "auto_promote": False,
        "online_learning": False,
    }, source="ai", quality="VALID" if champion else "UNAVAILABLE",
        timestamp=champion.training_timestamp if champion else None)


# ------------------------------------ Phase 14: forward observation and learning
# Read-only. The 24/7 driver runs as a separate process
# (scripts/run_observation_driver.py); the API reports what it recorded and adds
# no write route, so the sanctioned-writes invariant is unchanged.

FORWARD_WINDOW_DAYS = 90


def _forward_entries(db: Session, *, days: int = FORWARD_WINDOW_DAYS,
                     limit: int = 5000) -> list[Any]:
    """Join outcomes back to their observations so accuracy can be measured."""
    from ai.performance.rolling import PerformanceEntry

    repository = ForwardObservationRepository(db)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    entries: list[Any] = []
    for row in repository.outcomes_since(since, limit=limit):
        observation = repository.get_observation(row.observation_id)
        payload = dict(row.outcome_json or {})
        actual = payload.get("actual_direction")
        predicted = (observation.direction if observation else row.direction) or ""
        correct = None
        if actual:
            predicted_up = predicted.upper() in {"BUY", "LONG", "UP"}
            predicted_down = predicted.upper() in {"SELL", "SHORT", "DOWN"}
            if predicted_up or predicted_down:
                correct = actual == ("UP" if predicted_up else "DOWN")
        entries.append(PerformanceEntry(
            observation_id=row.observation_id, resolved_at=row.resolved_at,
            net_pnl=float(row.net_hypothetical_pnl or 0.0), mae=row.mae, mfe=row.mfe,
            correct=correct,
            confidence=(observation.nn_confidence if observation else None),
            spread=row.spread, regime=row.regime, session=row.session,
            timeframe=row.timeframe))
    return entries


@app.get("/observation/driver")
def observation_driver_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Configured schedule plus what the loop has actually recorded."""
    from observation.driver import ALLOWED_INTERVALS, DriverConfig

    settings = get_settings()
    config = DriverConfig.from_settings(settings)
    repository = ForwardObservationRepository(db)
    counts = repository.status_counts()
    recent = repository.recent_observations(1)
    return {
        "enabled": settings.observation_driver_enabled,
        "observation_mode": settings.observation_mode,
        "config": config.as_dict(),
        "allowed_intervals": list(ALLOWED_INTERVALS),
        "cycles_per_minute": round(60.0 / max(config.interval_seconds, 1), 4),
        "status_counts": counts,
        "observations": sum(counts.values()),
        "last_observation": recent[0].timestamp if recent else None,
        "automated_trading": False,
        "orders_sent": 0,
    }


@app.get("/observation/observations")
def observation_list(limit: int = Query(100, ge=1, le=500),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = ForwardObservationRepository(db).recent_observations(limit)
    return {"items": [as_dict(row) for row in rows], "count": len(rows),
            "evidence": "FORWARD_OBSERVATION"}


@app.get("/observation/outcomes")
def observation_outcomes(limit: int = Query(100, ge=1, le=500),
                         db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = ForwardObservationRepository(db).recent_outcomes(limit)
    return {"items": [as_dict(row) for row in rows], "count": len(rows),
            "primary_metric": "net_hypothetical_pnl", "evidence": "FORWARD_OBSERVATION"}


@app.get("/ai/performance")
def ai_performance(db: Session = Depends(get_db)) -> dict[str, Any]:
    from ai.performance.rolling import RollingPerformance

    entries = _forward_entries(db)
    summary = RollingPerformance().summary(entries, now=datetime.now(timezone.utc))
    return {**summary, "evidence": "FORWARD_OBSERVATION", "backtest": False}


@app.get("/ai/learning/segments")
def ai_learning_segments(db: Session = Depends(get_db)) -> dict[str, Any]:
    from ai.performance.segments import ForwardSegmentLearner

    entries = _forward_entries(db)
    return {"samples": len(entries), "evidence": "FORWARD_OBSERVATION",
            **ForwardSegmentLearner().all_dimensions(entries)}


@app.get("/ai/errors")
def ai_errors(limit: int = Query(200, ge=1, le=1000),
              db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = ForwardObservationRepository(db)
    rows = repository.recent_errors(limit)
    high = [row for row in rows if row.high_confidence_failure]
    by_class: dict[str, int] = {}
    for row in rows:
        by_class[row.error_class] = by_class.get(row.error_class, 0) + 1
    return {"items": [as_dict(row) for row in rows], "count": len(rows),
            "by_class": by_class, "high_confidence_failures": len(high),
            "high_confidence_threshold":
                float(load_yaml().get("phase_14", {}).get("high_confidence_threshold", 0.75))}


@app.get("/ai/edge")
def ai_edge(symbol: str = Query(None), db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = ForwardObservationRepository(db)
    latest = repository.latest_edge(symbol)
    return {
        "verdict": latest.verdict if latest else "INSUFFICIENT_DATA",
        "samples": latest.samples if latest else 0,
        "evidence": latest.evidence if latest else "FORWARD_OBSERVATION",
        "latest": as_dict(latest) if latest else None,
        "history": [as_dict(row) for row in repository.recent_edge(20)],
        "required_baselines": list(EDGE_REQUIRED_BASELINES),
        "backtest_accepted": False,
    }


@app.get("/ai/training/runs")
def ai_training_runs(limit: int = Query(20, ge=1, le=200),
                     db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = ForwardObservationRepository(db).recent_training_runs(limit)
    return {"items": [as_dict(row) for row in rows], "count": len(rows),
            "automatic_training": False, "promotion_requires_approval": True}


@app.get("/dashboard/forward")
def dashboard_forward(task: str = Query("direction"), symbol: str = Query("EURUSD"),
                      timeframe: str = Query("M5"),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    """Section 25: one payload for the forward observation panel."""
    from ai.performance.rolling import RollingPerformance
    from observation.driver import DriverConfig

    settings = get_settings()
    now = datetime.now(timezone.utc)
    forward = ForwardObservationRepository(db)
    learning = LearningRepository(db)
    observations = ObservationRepository(db)

    config = DriverConfig.from_settings(settings)
    counts = forward.status_counts()
    labelled = counts.get("LABELED", 0) + counts.get("DATASET_READY", 0)
    unlabelled = counts.get("OBSERVING", 0) + counts.get("HORIZON_REACHED", 0)
    failed = sum(count for status, count in counts.items()
                 if status in {"DATA_INVALID", "MODEL_ERROR", "CALCULATION_ERROR", "TIMEOUT"})

    recent = forward.recent_observations(1)
    successful = [row for row in forward.recent_observations(200)
                  if row.status not in {"DATA_INVALID", "MODEL_ERROR",
                                        "CALCULATION_ERROR", "TIMEOUT"}]

    key = ModelTask(task=task, symbol=symbol.upper(), timeframe=timeframe.upper()).key
    champion = learning.champion(key)
    challengers = learning.challengers(key)
    audit = learning.latest_dataset_audit()
    drift = learning.recent_drift(20)

    windows = RollingPerformance().evaluate(_forward_entries(db), now=now)
    errors = forward.recent_errors(500)
    edge = forward.latest_edge(symbol.upper())
    snapshot = dict((observations.latest_market_snapshot(symbol.upper()) or
                     type("Empty", (), {"snapshot_json": {}})()).snapshot_json or {})
    champion_payload = dict(champion.record_json or {}) if champion else {}

    return dashboard_envelope({
        "symbol": symbol.upper(),
        # driver
        "driver_enabled": settings.observation_driver_enabled,
        "observation_cycles": sum(counts.values()),
        "cycles_per_minute": round(60.0 / max(config.interval_seconds, 1), 4),
        "interval_seconds": config.interval_seconds,
        "last_cycle": recent[0].timestamp if recent else None,
        "last_successful_cycle": successful[0].timestamp if successful else None,
        "failed_cycles": failed,
        "status_counts": counts,
        # dataset
        "dataset_size": audit.row_count if audit else 0,
        "labeled_observations": labelled,
        "unlabeled_observations": unlabelled,
        # models
        "current_champion": champion.model_id if champion else None,
        "current_challenger": challengers[0].model_id if challengers else None,
        "model_accuracy": champion_payload.get("test_metrics", {}).get("accuracy"),
        "model_calibration": champion_payload.get("calibration", {}),
        # forward performance
        "performance_7d": windows["7d"].as_dict(),
        "performance_30d": windows["30d"].as_dict(),
        "performance_90d": windows["90d"].as_dict(),
        # edge, drift, failures
        "edge_status": edge.verdict if edge else "INSUFFICIENT_DATA",
        "edge_samples": edge.samples if edge else 0,
        "model_drift": sum(1 for row in drift if row.flagged),
        "drift_action": "FLAG_ONLY",
        "high_confidence_failures": sum(1 for row in errors if row.high_confidence_failure),
        # current market view
        "current_regime": (snapshot.get("regime") or {}).get("regime", "UNKNOWN"),
        "current_session": (snapshot.get("sessions") or {}).get("session", "UNKNOWN"),
        "nn_prediction": snapshot.get("neural_network"),
        "strategy": snapshot.get("strategy", {}),
        "risk": snapshot.get("risk", {}),
        "execution": snapshot.get("execution", {}),
        # invariants
        "evidence": "FORWARD_OBSERVATION",
        "automatic_training": False,
        "automated_trading": False,
        "orders_sent": 0,
    }, source="forward_observation",
        quality="VALID" if sum(counts.values()) else "UNAVAILABLE",
        timestamp=recent[0].timestamp if recent else None)


# ------------------------------------------------ Phase 15: AI research lab
# Read-only. Studies run as a separate job (scripts/run_research_lab.py) and
# write to reports/research/; the API reports what was recorded. No write route
# is added, so the sanctioned-writes invariant is unchanged.


def _research_observations(db: Session, *, days: int = 180,
                           limit: int = 20000) -> list[Any]:
    """Forward outcomes joined to their observations, as research rows."""
    from research.models import ResearchObservation

    forward = ForwardObservationRepository(db)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows: list[Any] = []
    for row in forward.outcomes_since(since, limit=limit):
        observation = forward.get_observation(row.observation_id)
        overrides: dict[str, Any] = {}
        if observation is not None:
            overrides["confidence"] = observation.nn_confidence
            overrides["strategy_id"] = observation.strategy
        rows.append(ResearchObservation.from_row(row, **overrides))
    return rows


@app.get("/research/strategies")
def research_strategies(status: str = Query(None),
                        limit: int = Query(200, ge=1, le=1000),
                        db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = ResearchRepository(db)
    rows = repository.strategies(status.upper() if status else None, limit)
    return {"items": [as_dict(row) for row in rows], "count": len(rows),
            "by_status": repository.strategy_counts(),
            "promotion_requires_approval": True, "executes": False}


@app.get("/research/experiments")
def research_experiments(limit: int = Query(200, ge=1, le=1000),
                         db: Session = Depends(get_db)) -> dict[str, Any]:
    repository = ResearchRepository(db)
    rows = repository.experiments(limit)
    return {"items": [as_dict(row) for row in rows], "count": len(rows),
            "experiment_count": repository.experiment_count(),
            "holdout_usage": repository.holdout_usage(),
            "evidence": "FORWARD_OBSERVATION"}


@app.get("/research/findings")
def research_findings(study: str = Query(None),
                      limit: int = Query(200, ge=1, le=1000),
                      db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = ResearchRepository(db).findings(study, limit)
    return {"items": [as_dict(row) for row in rows], "count": len(rows)}


@app.get("/research/champion")
def research_champion(db: Session = Depends(get_db)) -> dict[str, Any]:
    from research.champion import rejection_criteria

    repository = ResearchRepository(db)
    champion = repository.champion_strategy()
    challengers = [row for row in repository.strategies()
                   if row.status in {"VALIDATED", "TESTING"}]
    return {
        "champion": as_dict(champion) if champion else None,
        "challengers": [as_dict(row) for row in challengers],
        "challenger_count": len(challengers),
        "promoted_automatically": False, "requires_human_approval": True,
        **rejection_criteria(),
    }


@app.get("/dashboard/research")
def dashboard_research(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Section 23: one payload for the research panel."""
    from research.champion import rejection_criteria

    repository = ResearchRepository(db)
    forward = ForwardObservationRepository(db)
    learning = LearningRepository(db)

    champion = repository.champion_strategy()
    challengers = [row for row in repository.strategies()
                   if row.status in {"VALIDATED", "TESTING"}]
    best = repository.best_experiment()
    edge = forward.latest_edge()
    errors = forward.recent_errors(500)
    model_champion = learning.champion(
        ModelTask(task="direction", symbol="EURUSD", timeframe="M5").key)

    def finding(study: str) -> dict[str, Any]:
        row = repository.latest_finding(study)
        if row is None:
            return {"verdict": "NOT_EVALUATED", "sample_size": 0, "significant": False}
        return {"verdict": row.verdict, "sample_size": row.sample_size,
                "significant": row.significant, "effect_size": row.effect_size,
                "subject": row.subject}

    experiment_count = repository.experiment_count()
    report_payload = (repository.latest_finding("edge") or None)
    edge_report = dict(getattr(report_payload, "finding_json", {}) or {})

    return dashboard_envelope({
        # champions
        "champion_strategy": champion.key if champion else None,
        "champion_model": model_champion.model_id if model_champion else None,
        "challenger": challengers[0].key if challengers else None,
        "challenger_count": len(challengers),
        # experiments
        "experiment_count": experiment_count,
        "best_strategy": best.name if best else None,
        "best_strategy_expectancy": best.expectancy if best else None,
        # matrices
        "best_regime": finding("regime_matrix").get("subject"),
        "best_session": finding("session_matrix").get("subject"),
        "best_timeframe": finding("timeframe_matrix").get("subject"),
        # value studies
        "nn_value": finding("nn_value"),
        "indicator_value": finding("indicator_value"),
        "dca_value": finding("dca"),
        "time_exit_value": finding("time_exit"),
        # rigour
        "edge_status": edge.verdict if edge else "INSUFFICIENT_DATA",
        "confidence_interval": edge_report.get("confidence_interval")
        or (dict(edge.report_json or {}).get("metrics", {}).get("confidence_interval")
            if edge else None),
        "sample_size": edge.samples if edge else 0,
        "maximum_drawdown": best.maximum_drawdown if best else None,
        "high_confidence_failures": sum(1 for row in errors
                                        if row.high_confidence_failure),
        "holdout_usage": repository.holdout_usage(),
        "multiple_testing_note": ("Apparent edge grows with the number of strategies "
                                  "tried; the ledger records every one."),
        # invariants
        "evidence": "FORWARD_OBSERVATION",
        "promoted_automatically": False,
        "requires_human_approval": True,
        "automated_trading": False,
        "orders_sent": 0,
        "rejection_criteria": rejection_criteria()["criteria"],
    }, source="research",
        quality="VALID" if experiment_count else "UNAVAILABLE",
        timestamp=best.created_at if best else None)


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
