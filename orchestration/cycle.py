"""The smallest orchestration loop that makes the existing components run end to end.

One tick, one symbol:

    provider/data -> validation -> market snapshot -> intelligence
        -> optional AI inference -> strategy evaluation -> risk gate
        -> paper execution -> persistence -> alerts -> dashboard

Safety properties this module must preserve, none of which it invents:

* Only CLOSED candles enter it. `RealMarketSnapshotEngine` drops unclosed candles
  and anything stamped after `as_of`; `MarketIntelligenceService` queries with
  `closed_only=True`. This module adds no candle source of its own.
* No future data. The strategy engine already raises on a timeframe state or a
  prediction stamped after the snapshot, and paper execution rejects an order
  whose `source_timestamp` is after its execution timestamp. Both paths are used
  here rather than bypassed.
* No broker route. The only execution call is `PaperTradingService`, whose
  `EnvironmentSafetyLock` refuses anything but `TradingEnvironment.PAPER`.
* No fabricated intelligence. When a trained model is unavailable the cycle passes
  `prediction=None` and lets the existing risk gate raise MODEL_UNAVAILABLE. It
  never substitutes a default, a prior, or a random probability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any

from ai.inference import NeuralInferenceEngine
from ai.models.registry import ImmutableModelRegistry
from config.settings import ROOT, load_yaml
from data_quality import DataValidationError
from data_sources.gateway import DatabaseMarketDataProvider
from data_sources.snapshot import RealMarketSnapshotEngine
from database.repositories import AlertRepository, StrategyRepository
from features.intelligence import MarketIntelligenceService
from monitoring.alerts import AlertEngine, AlertRepositoryNotificationProvider, AlertRouter
from paper.execution import PositionSizingEngine
from paper.models import Direction, OrderType, PaperOrderRequest, PaperServiceState
from strategy import SetupDirection, StrategyIntelligenceEngine
from strategy.models import FEATURE_VERSION, STRATEGY_VERSION

logger = logging.getLogger(__name__)


class Stage(StrEnum):
    MARKET_DATA = "MARKET_DATA"
    VALIDATION = "VALIDATION"
    INTELLIGENCE = "INTELLIGENCE"
    INFERENCE = "INFERENCE"
    STRATEGY = "STRATEGY"
    PAPER_EXECUTION = "PAPER_EXECUTION"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class CycleResult:
    """What one tick observed. `executed` is always a paper result or None."""

    timestamp: datetime
    symbol: str
    stage: Stage
    halted: bool
    reason_codes: tuple[str, ...] = ()
    source_timestamp: datetime | None = None
    data_quality: str = "UNAVAILABLE"
    provider_status: str = "UNKNOWN"
    prediction: dict[str, Any] | None = None
    model_status: str = "UNAVAILABLE"
    decision: str | None = None
    setup_status: str | None = None
    executed: Any = None
    alerts: tuple[Any, ...] = field(default_factory=tuple)
    environment: str = "PAPER"


class OrchestrationCycle:
    """Runs one end-to-end tick against a database session.

    The cycle owns no candles, no broker and no model of its own: it wires the
    existing engines together and records what they decided.
    """

    def __init__(
        self,
        session,
        *,
        paper_service,
        strategy: StrategyIntelligenceEngine | None = None,
        sizing: PositionSizingEngine | None = None,
        inference: Any = None,
        model_registry_path: str | Path | None = None,
        model_version: str | None = None,
        fixed_position_size: float | None = None,
        memory: dict[str, Any] | None = None,
        now: datetime | None = None,
    ):
        config = load_yaml().get("phase_9", {}).get("orchestration", {})
        self.session = session
        self.paper = paper_service
        self.strategy = strategy or StrategyIntelligenceEngine()
        self.sizing = sizing or PositionSizingEngine()
        # An injected predictor replaces the registry lookup; production leaves it None
        # so that a missing trained model stays a missing model.
        self.inference = inference
        self.intelligence = MarketIntelligenceService(session)
        self.market = RealMarketSnapshotEngine(DatabaseMarketDataProvider(session))
        self.strategy_repository = StrategyRepository(session)
        self.alerts = AlertRouter(AlertEngine(AlertRepositoryNotificationProvider(AlertRepository(session))))
        self.model_version = model_version if model_version is not None else config.get("model_version")
        self.model_registry_path = Path(
            model_registry_path or config.get("model_registry_path") or ROOT / "data" / "models",
        )
        self.fixed_position_size = float(
            fixed_position_size if fixed_position_size is not None else config.get("fixed_position_size", 0.1),
        )
        self._now = now
        # A runner builds a fresh cycle per tick with its own session, so the
        # bar-dedup and kill-switch-transition state is handed in rather than reset.
        self._memory = memory if memory is not None else {}
        self._last_processed: dict[str, datetime] = self._memory.setdefault("last_processed", {})
        self._memory.setdefault("kill_switch", bool(getattr(self.paper.risk.kill_switch, "enabled", False)))

    # ------------------------------------------------------------------ helpers
    def _clock(self) -> datetime:
        return self._now or datetime.now(timezone.utc)

    def _halt(self, symbol, stage, reasons, **extra) -> CycleResult:
        return CycleResult(self._clock(), symbol, stage, True, tuple(reasons), **extra)

    def _report_kill_switch(self) -> None:
        """Emit once on each transition rather than on every tick."""
        enabled = bool(getattr(self.paper.risk.kill_switch, "enabled", False))
        if enabled != self._memory.get("kill_switch"):
            self.alerts.kill_switch(enabled=enabled, timestamp=self._clock())
            self._memory["kill_switch"] = enabled

    def _predict(self, snapshot):
        """Return (prediction, status). A missing or incompatible model yields None."""
        if self.inference is None and not self.model_version:
            return None, "UNAVAILABLE"
        try:
            engine = self.inference
            if engine is None:
                model, metadata = ImmutableModelRegistry(self.model_registry_path).load(self.model_version)
                engine = NeuralInferenceEngine(model, metadata)
            prediction = engine.predict(snapshot)
        except (FileNotFoundError, OSError, KeyError, ValueError) as error:
            logger.warning("model inference unavailable for %s: %s", snapshot.symbol, error)
            return None, "UNAVAILABLE"
        if prediction.timestamp > snapshot.timestamp:
            logger.error("model returned a future prediction for %s; discarded", snapshot.symbol)
            return None, "UNAVAILABLE"
        self.strategy_repository.save_prediction(prediction)
        return prediction, "ONLINE"

    # ------------------------------------------------------------------ the tick
    def run(self, symbol: str) -> CycleResult:
        symbol = symbol.upper()
        now = self._clock()
        self._report_kill_switch()

        # 1. provider + market data, closed candles only.
        market = self.market.build(symbol, as_of=now)
        provider_status = "OFFLINE" if "PROVIDER_UNAVAILABLE" in market.reasons else "ONLINE"
        data_quality = "INVALID" if any(
            reason.startswith("DATA_QUALITY_INVALID") for reason in market.reasons
        ) else "VALID"

        # 2. validation gate. Nothing downstream runs on rejected data.
        if not market.strategy_allowed:
            if provider_status != "ONLINE":
                self.alerts.provider_unavailable(provider="market_gateway", status=provider_status,
                                                 timestamp=now, symbol=symbol)
            if data_quality != "VALID":
                self.alerts.data_quality_failure(symbol=symbol, detail=", ".join(market.reasons), timestamp=now)
            return self._halt(symbol, Stage.VALIDATION, market.reasons, source_timestamp=market.timestamp,
                              data_quality=data_quality, provider_status=provider_status)

        # 3. intelligence over closed candles.
        try:
            snapshot = self.intelligence.calculate(symbol, as_of=now)
        except (ValueError, DataValidationError) as error:
            self.alerts.data_quality_failure(symbol=symbol, detail=str(error), timestamp=now)
            return self._halt(symbol, Stage.INTELLIGENCE, ("INTELLIGENCE_UNAVAILABLE",),
                              data_quality=data_quality, provider_status=provider_status)
        if not any(state.available for state in snapshot.timeframes.values()):
            return self._halt(symbol, Stage.INTELLIGENCE, ("NO_TIMEFRAME_INTELLIGENCE",),
                              source_timestamp=snapshot.timestamp, data_quality="UNAVAILABLE",
                              provider_status=provider_status)

        # One evaluation per closed bar; a faster poll must not re-trade the same bar.
        if self._last_processed.get(symbol) == snapshot.timestamp:
            return self._halt(symbol, Stage.INTELLIGENCE, ("ALREADY_EVALUATED_THIS_CANDLE",),
                              source_timestamp=snapshot.timestamp, data_quality=data_quality,
                              provider_status=provider_status)

        quote = market.quote or {}
        entry_price = quote.get("mid_price")
        if entry_price is None and quote.get("bid") is not None and quote.get("ask") is not None:
            entry_price = (float(quote["bid"]) + float(quote["ask"])) / 2
        if entry_price is None:
            return self._halt(symbol, Stage.MARKET_DATA, ("QUOTE_UNAVAILABLE",),
                              source_timestamp=snapshot.timestamp, data_quality=data_quality,
                              provider_status=provider_status)

        self.strategy_repository.save_snapshot(snapshot, strategy_version=STRATEGY_VERSION,
                                               feature_version=FEATURE_VERSION)

        # 4. optional inference. No model means no fabricated probabilities.
        prediction, model_status = self._predict(snapshot)

        # 5. strategy evaluation and its risk gate.
        decision = self.strategy.evaluate(snapshot, entry_price=float(entry_price), prediction=prediction)
        self.strategy_repository.save_setup(decision.setup)
        self.strategy_repository.save_decision(decision)
        self.alerts.strategy_decision(decision, timestamp=snapshot.timestamp)
        self._last_processed[symbol] = snapshot.timestamp

        prediction_json = self.strategy_repository.jsonable(prediction) if prediction else None
        common = {
            "source_timestamp": snapshot.timestamp, "data_quality": data_quality,
            "provider_status": provider_status, "prediction": prediction_json,
            "model_status": model_status, "decision": decision.decision,
            "setup_status": decision.setup.status.value,
        }

        if decision.decision != "SIMULATE":
            return CycleResult(now, symbol, Stage.STRATEGY, False, decision.reason_codes, **common)

        # 6. paper execution. Every gate below already exists; none is bypassed.
        if self.paper.state is not PaperServiceState.RUNNING:
            return CycleResult(now, symbol, Stage.STRATEGY, False,
                               (*decision.reason_codes, "PAPER_TRADING_NOT_RUNNING"), **common)
        if any(position.symbol == symbol for position in self.paper.positions.values()):
            return CycleResult(now, symbol, Stage.STRATEGY, False,
                               (*decision.reason_codes, "HOLDING_OPEN_POSITION"), **common)

        direction = Direction.LONG if decision.setup.direction is SetupDirection.LONG else Direction.SHORT
        quantity = self.sizing.calculate("fixed_size", balance=self.paper.account.balance,
                                         price=float(entry_price), fixed_size=self.fixed_position_size)
        if quantity <= 0:
            return CycleResult(now, symbol, Stage.STRATEGY, False,
                               (*decision.reason_codes, "POSITION_SIZE_ZERO"), **common)

        request = PaperOrderRequest(
            symbol, direction, OrderType.MARKET, quantity, now,
            strategy_version=decision.strategy_version, model_version=decision.setup.model_version,
            source_timestamp=snapshot.timestamp,
        )
        volatility = str((snapshot.timeframes["M15"].volatility or {}).get("state", "NORMAL_VOLATILITY")) \
            if "M15" in snapshot.timeframes else "NORMAL_VOLATILITY"
        executed = self.paper.enter(
            request, quote=market.quote, setup_status=decision.setup.status.value,
            risk_decision=decision.setup.risk_context, data_quality=data_quality,
            provider_status=provider_status, prediction=prediction_json, volatility=volatility,
            news_risk=market.news_risk, reasons=decision.reason_codes,
            market_context={"symbol": symbol, "direction": direction.value,
                            "regime": decision.setup.market_regime, "session": market.market_session,
                            "d1_bias": decision.setup.market_regime},
            mtf_context={"alignment": decision.setup.timeframe_alignment},
            liquidity_context=decision.setup.liquidity_context,
            indicator_context=decision.setup.indicator_context,
        )
        alerts = self.alerts.execution_result(executed, symbol=symbol, timestamp=now, action="ENTRY")
        return CycleResult(now, symbol, Stage.COMPLETED if executed.accepted else Stage.PAPER_EXECUTION,
                           False, (*decision.reason_codes, *executed.reason_codes),
                           executed=executed, alerts=tuple(alerts), **common)
