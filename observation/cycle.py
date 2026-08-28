"""One observation cycle against the live market.

    MT5 -> market data -> D1..M5 -> data quality -> indicators -> structure
        -> liquidity -> regime -> NN -> strategy -> risk -> execution SIMULATION
        -> snapshot -> dashboard -> monitoring -> alerting

Nothing in this module can place an order. Its terminal stage is
`ExecutionSimulator`, which has no transport, and the paper/live engines are not
imported at all. The cycle is the Phase 12 equivalent of Phase 9's
OrchestrationCycle, but it stops at a recorded simulation instead of a paper fill.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from config.settings import Settings, get_settings, load_yaml
from data_quality import DataValidationError
from execution.mt5.account import MT5Account
from features.intelligence import MarketIntelligenceService
from features.session import SessionEngine
from observation.dca_analysis import DCAAnalyzer
from observation.demo_account import DemoAccountResult, DemoAccountValidator, DemoValidation
from observation.health import ComponentHealth, SystemHealthMonitor
from observation.liquidity_evidence import LiquidityEvidenceClassifier
from observation.quality_gate import DataQualityGate, GateResult, GateVerdict
from observation.regime import MarketRegime, MarketRegimeEngine
from observation.simulation import ExecutionSimulator, SignalAction
from observation.snapshot import FeatureSnapshot, MarketSnapshot, new_cycle_id
from observation.time_exit import TimeExitAnalyzer
from strategy import StrategyIntelligenceEngine
from strategy.models import SetupDirection, SetupStatus

logger = logging.getLogger(__name__)

# Maps the strategy engine's internal verdict onto the Phase 12 signal vocabulary.
DECISION_TO_SIGNAL = {"SIMULATE": None, "WAIT": SignalAction.WAIT, "INVALIDATE": SignalAction.EXIT}


class CycleStage:
    ACCOUNT = "ACCOUNT"
    MARKET_DATA = "MARKET_DATA"
    DATA_QUALITY = "DATA_QUALITY"
    INTELLIGENCE = "INTELLIGENCE"
    REGIME = "REGIME"
    INFERENCE = "INFERENCE"
    STRATEGY = "STRATEGY"
    SIMULATION = "SIMULATION"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class ObservationResult:
    cycle_id: str
    symbol: str
    timestamp: datetime
    stage: str
    halted: bool
    reasons: tuple[str, ...] = ()
    account: DemoAccountResult | None = None
    quality: dict[str, GateResult] = field(default_factory=dict)
    regime: Any = None
    signal: SignalAction = SignalAction.WAIT
    simulation: Any = None
    snapshot: FeatureSnapshot | None = None
    market: MarketSnapshot | None = None
    health: Any = None
    alerts: tuple[Any, ...] = ()
    orders_sent: int = 0

    @property
    def signal_allowed(self) -> bool:
        return not self.halted

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle_id": self.cycle_id, "symbol": self.symbol, "timestamp": self.timestamp,
            "stage": self.stage, "halted": self.halted, "reasons": list(self.reasons),
            "signal": str(self.signal), "orders_sent": 0,
            "account": self.account.as_dict() if self.account else None,
            "data_quality": {name: result.as_dict() for name, result in self.quality.items()},
            "regime": self.regime.as_dict() if self.regime else None,
            "execution_simulation": self.simulation.as_dict() if self.simulation else None,
            "health": self.health.as_dict() if self.health else None,
        }


class ObservationCycle:
    def __init__(self, session, *, client: Any = None, settings: Settings | None = None,
                 strategy: StrategyIntelligenceEngine | None = None,
                 inference: Any = None, alerts: Any = None, repository: Any = None):
        self.settings = settings or get_settings()
        config = load_yaml().get("phase_12", {})
        self.session = session
        self.client = client
        self.timeframes = tuple(config.get("timeframes") or ("D1", "H4", "H1", "M30", "M15", "M5"))
        self.intelligence = MarketIntelligenceService(session) if session is not None else None
        self.strategy = strategy or StrategyIntelligenceEngine()
        self.inference = inference
        self.alerts = alerts
        self.repository = repository
        self.account_validator = DemoAccountValidator(self.settings)
        self.gate = DataQualityGate(
            minimum_candles=int(config.get("minimum_candles", 60)),
            freshness_multiplier=float(config.get("freshness_multiplier", 3)))
        self.regime_engine = MarketRegimeEngine()
        self.liquidity_classifier = LiquidityEvidenceClassifier()
        self.simulator = ExecutionSimulator(self.settings)
        self.dca = DCAAnalyzer()
        self.time_exit = TimeExitAnalyzer()
        self.sessions = SessionEngine()
        self.health_monitor = SystemHealthMonitor()
        self._last_error: str | None = None

    # ------------------------------------------------------------------ helpers
    def _now(self) -> datetime:
        if self.client is not None and hasattr(self.client, "now"):
            return self.client.now()
        return datetime.now(timezone.utc)

    def _alert(self, method: str, **kwargs: Any) -> tuple[Any, ...]:
        if self.alerts is None:
            return ()
        handler = getattr(self.alerts, method, None)
        if handler is None:
            return ()
        try:
            return tuple(handler(**kwargs) or ())
        except Exception:
            logger.exception("observation alert %s failed", method)
            return ()

    def _health(self, **reported: Any):
        return self.health_monitor.build(
            {"api": ComponentHealth.HEALTHY,
             "database": ComponentHealth.HEALTHY if self.session is not None else ComponentHealth.UNKNOWN,
             "dashboard": ComponentHealth.HEALTHY,
             "monitoring": ComponentHealth.HEALTHY if self.alerts is not None else ComponentHealth.UNKNOWN,
             "execution": ComponentHealth.HEALTHY, **reported},
            last_error=self._last_error, now=self._now())

    def _halt(self, cycle_id, symbol, stage, reasons, **extra) -> ObservationResult:
        return ObservationResult(cycle_id, symbol, self._now(), stage, True,
                                 tuple(str(reason) for reason in reasons), **extra)

    # ------------------------------------------------------------------- cycle
    def run(self, symbol: str) -> ObservationResult:
        """Run one full cycle. Never raises for market conditions; never sends an order."""
        cycle_id = new_cycle_id()
        symbol = symbol.upper()
        now = self._now()
        self._last_error = None

        # 1. MT5 + DEMO account verification.
        account_result = self.account_validator.validate_client(self.client)
        if account_result.status is DemoValidation.INVALID_ACCOUNT:
            self._alert("real_account_detected", account=account_result)
        if not account_result.valid:
            health = self._health(mt5=ComponentHealth.FAILED, market_data=ComponentHealth.UNKNOWN,
                                  data_quality=ComponentHealth.UNKNOWN,
                                  strategy=ComponentHealth.UNKNOWN, nn=ComponentHealth.UNKNOWN,
                                  risk=ComponentHealth.UNKNOWN)
            alerts = self._alert("mt5_disconnected", reasons=account_result.reasons) \
                if account_result.status is DemoValidation.CONNECTION_ERROR else ()
            return self._halt(cycle_id, symbol, CycleStage.ACCOUNT, account_result.reasons,
                              account=account_result, health=health, alerts=alerts)
        self._alert("demo_account_valid", account=account_result)

        # 2. Market data: D1 -> M5, closed candles only.
        batches: dict[str, list[dict[str, Any]]] = {}
        unavailable: list[str] = []
        for timeframe in self.timeframes:
            result = self.client.get_rates(symbol, timeframe, 300)
            if result.ok and result.data:
                batches[timeframe] = list(result.data)
            else:
                unavailable.append(f"{timeframe}:{result.code}")
        tick = self.client.get_tick(symbol)
        quote = tick.data if tick.ok else None

        if not batches:
            health = self._health(mt5=ComponentHealth.HEALTHY, market_data=ComponentHealth.FAILED,
                                  data_quality=ComponentHealth.UNKNOWN)
            alerts = self._alert("stale_market_data", symbol=symbol, reasons=tuple(unavailable))
            return self._halt(cycle_id, symbol, CycleStage.MARKET_DATA,
                              ("NO_MARKET_DATA", *unavailable),
                              account=account_result, health=health, alerts=alerts)

        # 3. Data-quality gate. A FAIL means no signal is produced at all.
        quality = self.gate.evaluate_all(batches, symbol=symbol, as_of=now)
        quality_ok = DataQualityGate.signal_allowed(quality) and not unavailable
        if not DataQualityGate.signal_allowed(quality):
            failed = {name: result.reasons for name, result in quality.items()
                      if result.verdict is GateVerdict.FAIL}
            health = self._health(mt5=ComponentHealth.HEALTHY,
                                  market_data=ComponentHealth.DEGRADED,
                                  data_quality=ComponentHealth.FAILED,
                                  strategy=ComponentHealth.UNKNOWN)
            alerts = self._alert("data_quality_failed", symbol=symbol, failures=failed)
            reasons = ["DATA_QUALITY_FAILED"] + [f"{name}:{','.join(codes)}"
                                                 for name, codes in failed.items()]
            return self._halt(cycle_id, symbol, CycleStage.DATA_QUALITY, reasons,
                              account=account_result, quality=quality, health=health, alerts=alerts)

        # 4. Intelligence: structure, liquidity, indicators, volatility, sessions.
        snapshot = None
        if self.intelligence is not None:
            try:
                snapshot = self.intelligence.calculate(symbol, as_of=now)
            except (ValueError, DataValidationError) as error:
                self._last_error = f"INTELLIGENCE:{type(error).__name__}"
                logger.warning("intelligence unavailable for %s: %s", symbol, error)

        regime = self.regime_engine.from_snapshot(snapshot) if snapshot else None
        liquidity = (self.liquidity_classifier.from_timeframes(snapshot.timeframes, symbol=symbol)
                     if snapshot else None)
        session_context = self.sessions.session_for(now)

        # 5. Optional AI inference. A missing model is never substituted.
        prediction = None
        model_state = ComponentHealth.UNKNOWN
        if self.inference is not None and snapshot is not None:
            try:
                candidate = self.inference.predict(snapshot)
                if candidate.timestamp <= snapshot.timestamp:
                    prediction = candidate
                    model_state = ComponentHealth.HEALTHY
                else:
                    self._last_error = "MODEL_RETURNED_FUTURE_PREDICTION"
                    model_state = ComponentHealth.FAILED
            except Exception as error:
                self._last_error = f"MODEL:{type(error).__name__}"
                model_state = ComponentHealth.FAILED
                logger.warning("model inference failed: %s", error)
                self._alert("model_failure", symbol=symbol, detail=str(error))

        # 6. Strategy + its risk gate.
        decision = None
        entry_price = None
        if quote:
            mid = quote.get("mid_price")
            entry_price = float(mid) if mid is not None else None
        if snapshot is not None and entry_price is not None:
            try:
                decision = self.strategy.evaluate(snapshot, entry_price=entry_price,
                                                  prediction=prediction)
            except ValueError as error:
                self._last_error = f"STRATEGY:{type(error).__name__}"
                logger.warning("strategy evaluation refused: %s", error)

        signal = self._signal_for(decision, regime)
        risk_allowed = bool(decision and decision.setup.risk_context.risk_allowed)
        risk_reasons = tuple(decision.setup.risk_context.reason_codes) if decision else ()
        if decision is not None:
            self._alert("strategy_signal", symbol=symbol, signal=str(signal), decision=decision)
        if not risk_allowed and decision is not None:
            self._alert("risk_block", symbol=symbol, reasons=risk_reasons)

        # 7. Execution SIMULATION. This is the terminal stage; nothing is sent.
        simulation = self.simulator.simulate(
            symbol=symbol, signal=signal, risk_approved=risk_allowed, risk_reasons=risk_reasons,
            data_quality_ok=quality_ok, demo_account_valid=account_result.valid,
            confidence=float(decision.setup.confidence.final_confidence) if decision else 0.0,
            entry=entry_price,
            context={"regime": str(regime.regime) if regime else str(MarketRegime.UNKNOWN),
                     "session": session_context.value, "cycle_id": cycle_id})
        if simulation.blocked and simulation.signal in {SignalAction.BUY, SignalAction.SELL}:
            self._alert("execution_blocked", symbol=symbol, reasons=simulation.reasons)

        # 8. Record the cycle.
        feature_snapshot = self._feature_snapshot(
            cycle_id, symbol, now, quote, batches, quality, snapshot, regime,
            liquidity, session_context, prediction, decision, simulation)
        market_snapshot = self._market_snapshot(feature_snapshot, cycle_id)
        health = self._health(
            mt5=ComponentHealth.HEALTHY, market_data=ComponentHealth.HEALTHY,
            data_quality=ComponentHealth.HEALTHY if quality_ok else ComponentHealth.DEGRADED,
            strategy=ComponentHealth.HEALTHY if decision else ComponentHealth.DEGRADED,
            nn=model_state, risk=ComponentHealth.HEALTHY if decision else ComponentHealth.UNKNOWN)

        if self.repository is not None:
            try:
                self.repository.save_cycle(feature_snapshot, market_snapshot, simulation, health)
            except Exception:
                logger.exception("failed to persist observation cycle %s", cycle_id)

        logger.info("observation cycle %s %s signal=%s execution=%s reason=%s orders_sent=0",
                    cycle_id, symbol, signal, simulation.execution, simulation.primary_reason)

        return ObservationResult(
            cycle_id, symbol, now, CycleStage.COMPLETED, False,
            tuple(simulation.reasons), account_result, quality, regime, signal,
            simulation, feature_snapshot, market_snapshot, health, orders_sent=0)

    # ------------------------------------------------------------------ mapping
    @staticmethod
    def _signal_for(decision: Any, regime: Any) -> SignalAction:
        """Translate the strategy verdict into the Phase 12 signal vocabulary."""
        if decision is None:
            return SignalAction.WAIT
        verdict = decision.decision
        if verdict == "INVALIDATE":
            return SignalAction.EXIT
        if verdict != "SIMULATE":
            return SignalAction.WAIT
        direction = decision.setup.direction
        if direction is SetupDirection.LONG:
            return SignalAction.BUY
        if direction is SetupDirection.SHORT:
            return SignalAction.SELL
        return SignalAction.WAIT

    # ---------------------------------------------------------------- snapshots
    def _feature_snapshot(self, cycle_id, symbol, now, quote, batches, quality, snapshot,
                          regime, liquidity, session, prediction, decision,
                          simulation) -> FeatureSnapshot:
        timeframes = {
            name: {
                "candles": len(candles),
                "last_candle": candles[-1]["timestamp"] if candles else None,
                "open": candles[-1]["open"] if candles else None,
                "high": candles[-1]["high"] if candles else None,
                "low": candles[-1]["low"] if candles else None,
                "close": candles[-1]["close"] if candles else None,
                "volume": candles[-1].get("volume") if candles else None,
                "quality": quality[name].verdict if name in quality else None,
                "age_seconds": quality[name].age_seconds if name in quality else None,
            }
            for name, candles in batches.items()
        }
        structure = {}
        indicators = {}
        volatility = {}
        if snapshot is not None:
            for name, state in snapshot.timeframes.items():
                structure[name] = {
                    "trend": state.trend, "structure": state.structure, "bos": state.bos,
                    "choch": state.choch, "swing_high": state.swing_high,
                    "swing_low": state.swing_low,
                }
                indicators[name] = dict(state.indicators or {})
                volatility[name] = dict(state.volatility or {})

        spread = {}
        if quote:
            spread = {"spread": quote.get("spread"), "spread_percent": quote.get("spread_percent"),
                      "state": quote.get("spread_state"), "average": quote.get("average_spread")}

        return FeatureSnapshot(
            cycle_id=cycle_id, symbol=symbol, timestamp=now,
            market_data={"bid": quote.get("bid") if quote else None,
                         "ask": quote.get("ask") if quote else None,
                         "mid_price": quote.get("mid_price") if quote else None,
                         "tick_time": quote.get("timestamp") if quote else None,
                         "source": "mt5"},
            timeframes=timeframes, structure=structure,
            liquidity=liquidity.as_dict() if liquidity else {},
            indicators=indicators,
            session={"session": session.value, "timestamp": now},
            regime=regime.as_dict() if regime else {},
            spread=spread, volatility=volatility,
            neural_network=({
                "prob_up": prediction.prob_up, "prob_down": prediction.prob_down,
                "prob_neutral": prediction.prob_neutral, "confidence": prediction.confidence,
                "model_version": prediction.model_version,
                "feature_version": prediction.feature_version,
                "timestamp": prediction.timestamp,
            } if prediction else None),
            strategy=({
                "decision": decision.decision, "status": str(decision.setup.status),
                "direction": str(decision.setup.direction),
                "score": decision.setup.setup_score.score,
                "confidence": decision.setup.confidence.final_confidence,
                "reason_codes": list(decision.reason_codes),
            } if decision else {}),
            risk=({"risk_allowed": decision.setup.risk_context.risk_allowed,
                   "reason_codes": list(decision.setup.risk_context.reason_codes)}
                  if decision else {}),
            data_quality={name: result.as_dict() for name, result in quality.items()},
            execution_simulation=simulation.as_dict(),
        )

    @staticmethod
    def _market_snapshot(feature: FeatureSnapshot, cycle_id: str) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=feature.symbol, timestamp=feature.timestamp, price=feature.market_data,
            spread=feature.spread, session=feature.session, regime=feature.regime,
            timeframes=feature.timeframes, structure=feature.structure,
            liquidity=feature.liquidity, indicators=feature.indicators,
            neural_network=feature.neural_network, strategy=feature.strategy,
            risk=feature.risk, execution=feature.execution_simulation,
            data_quality=feature.data_quality, cycle_id=cycle_id,
        )
