from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", "source", name="uq_market_candle_source"),
        Index("ix_market_candles_symbol_timeframe_timestamp", "symbol", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(24, 10), nullable=False)
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    tick_volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    spread: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown", server_default="unknown")
    provider_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ingestion_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    source_timeframe: Mapped[str | None] = mapped_column(String(8))
    target_timeframe: Mapped[str | None] = mapped_column(String(8))
    resampling_method: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    @property
    def ingested_at(self) -> datetime:
        """Canonical Phase 4 name backed by the existing Phase 2 ingestion_time column."""
        return self.ingestion_time


class MarketDataIngestion(Base):
    __tablename__ = "market_data_ingestions"
    __table_args__ = (
        Index("ix_market_data_ingestions_provider_end", "provider", "request_end"),
        Index("ix_market_data_ingestions_symbol_tf_end", "symbol", "timeframe", "request_end"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    request_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rows_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gaps: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    last_error: Mapped[str | None] = mapped_column(Text)


class MarketTick(Base):
    __tablename__ = "market_ticks"
    __table_args__ = (Index("ix_market_ticks_symbol_timestamp", "symbol", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    bid: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    last: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(24, 8))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TradingViewAlert(Base):
    __tablename__ = "tradingview_alerts"
    __table_args__ = (Index("ix_tv_alerts_symbol_timestamp", "symbol", "event_timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str | None] = mapped_column(String(8))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(32))
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="tradingview", nullable=False)


class LiquidityEvent(Base):
    __tablename__ = "liquidity_events"
    __table_args__ = (
        Index("ix_liquidity_symbol_tf_timestamp", "symbol", "timeframe", "timestamp"),
        Index("ix_liquidity_events_event_timestamp", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(32))
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    strength: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(64), nullable=False)


class StructureEvent(Base):
    __tablename__ = "structure_events"
    __table_args__ = (
        Index("ix_structure_symbol_tf_timestamp", "symbol", "timeframe", "timestamp"),
        Index("ix_structure_events_event_timestamp", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str | None] = mapped_column(String(32))
    price: Mapped[Decimal | None] = mapped_column(Numeric(24, 10))
    strength: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(64), nullable=False)


class IndicatorSnapshot(Base):
    __tablename__ = "indicator_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_indicator_snapshot"),
        Index("ix_indicator_symbol_tf_timestamp", "symbol", "timeframe", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    rsi: Mapped[float | None] = mapped_column(Float)
    adx: Mapped[float | None] = mapped_column(Float)
    di_plus: Mapped[float | None] = mapped_column(Float)
    di_minus: Mapped[float | None] = mapped_column(Float)
    atr: Mapped[float | None] = mapped_column(Float)
    ichimoku_tenkan: Mapped[float | None] = mapped_column(Float)
    ichimoku_kijun: Mapped[float | None] = mapped_column(Float)
    ichimoku_senkou_a: Mapped[float | None] = mapped_column(Float)
    ichimoku_senkou_b: Mapped[float | None] = mapped_column(Float)
    ichimoku_chikou: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class MarketIntelligenceSnapshot(Base):
    __tablename__ = "market_intelligence_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "event_timestamp", "calculation_version", name="uq_market_intelligence_snapshot"),
        Index("ix_intelligence_symbol_tf_timestamp", "symbol", "timeframe", "event_timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="MTF")
    market_candle_id: Mapped[int | None] = mapped_column(ForeignKey("market_candles.id", ondelete="SET NULL"))
    calculation_version: Mapped[str] = mapped_column(String(32), nullable=False)
    bias: Mapped[str] = mapped_column(String(32), nullable=False)
    trade_state: Mapped[str] = mapped_column(String(32), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    feature_vector_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class COTReport(Base):
    __tablename__ = "cot_reports"
    __table_args__ = (
        UniqueConstraint("report_date", "market", "contract", "source", name="uq_cot_report"),
        Index("ix_cot_market_report_date", "market", "report_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)
    market: Mapped[str] = mapped_column(String(255), nullable=False)
    contract: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    dealer_long: Mapped[int | None] = mapped_column(Integer)
    dealer_short: Mapped[int | None] = mapped_column(Integer)
    dealer_spread: Mapped[int | None] = mapped_column(Integer)
    asset_manager_long: Mapped[int | None] = mapped_column(Integer)
    asset_manager_short: Mapped[int | None] = mapped_column(Integer)
    asset_manager_spread: Mapped[int | None] = mapped_column(Integer)
    leveraged_money_long: Mapped[int | None] = mapped_column(Integer)
    leveraged_money_short: Mapped[int | None] = mapped_column(Integer)
    leveraged_money_spread: Mapped[int | None] = mapped_column(Integer)
    other_reportables_long: Mapped[int | None] = mapped_column(Integer)
    other_reportables_short: Mapped[int | None] = mapped_column(Integer)
    other_reportables_spread: Mapped[int | None] = mapped_column(Integer)
    non_reportables_long: Mapped[int | None] = mapped_column(Integer)
    non_reportables_short: Mapped[int | None] = mapped_column(Integer)
    non_reportables_spread: Mapped[int | None] = mapped_column(Integer)
    open_interest: Mapped[int | None] = mapped_column(Integer)
    raw_data_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class InstitutionalPressure(Base):
    __tablename__ = "institutional_pressure"
    __table_args__ = (Index("ix_pressure_symbol_tf_timestamp", "symbol", "timeframe", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    cot_score: Mapped[float | None] = mapped_column(Float)
    open_interest_score: Mapped[float | None] = mapped_column(Float)
    volume_score: Mapped[float | None] = mapped_column(Float)
    liquidity_score: Mapped[float | None] = mapped_column(Float)
    structure_score: Mapped[float | None] = mapped_column(Float)
    institutional_pressure_score: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class StrategySignal(Base):
    __tablename__ = "strategy_signals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class TradingOutcome(Base):
    __tablename__ = "trading_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(Integer)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[float | None] = mapped_column(Float)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class SimulatedTradeRecord(Base):
    __tablename__ = "simulated_trades"
    __table_args__ = (Index("ix_simulated_trades_entry_time", "entry_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    size: Mapped[float] = mapped_column(Float, nullable=False)
    pnl: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    counter_trend_trade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entries_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    evaluations_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketFeature(Base):
    __tablename__ = "market_features"
    __table_args__ = (
        UniqueConstraint("symbol", "base_timeframe", "timestamp", "feature_version", name="uq_market_feature_version"),
        Index("ix_market_features_symbol_timestamp", "symbol", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    base_timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="M15")
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    features_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MarketLabel(Base):
    __tablename__ = "market_labels"
    __table_args__ = (
        UniqueConstraint("symbol", "base_timeframe", "timestamp", "label_version", name="uq_market_label_version"),
        Index("ix_market_labels_symbol_timestamp", "symbol", "timestamp"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label_end_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    base_timeframe: Mapped[str] = mapped_column(String(8), nullable=False, default="M15")
    label_version: Mapped[str] = mapped_column(String(64), nullable=False)
    labels_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class DatasetMetadataRecord(Base):
    __tablename__ = "dataset_metadata"
    __table_args__ = (Index("ix_dataset_metadata_symbol_created", "symbol", "created_at"),)

    dataset_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    label_version: Mapped[str] = mapped_column(String(64), nullable=False)
    data_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class StrategyMarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class TradeSetupRecord(Base):
    __tablename__ = "trade_setups"
    setup_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64))
    setup_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class StrategyDecisionRecord(Base):
    __tablename__ = "strategy_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    setup_id: Mapped[str | None] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PredictionRecord(Base):
    __tablename__ = "predictions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prediction_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DCAEventRecord(Base):
    __tablename__ = "dca_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    setup_id: Mapped[str | None] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ExitDecisionRecord(Base):
    __tablename__ = "exit_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    setup_id: Mapped[str | None] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class StrategyBacktestRecord(Base):
    __tablename__ = "strategy_backtests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    strategy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

class MarketQuote(Base):
    __tablename__="market_quotes"
    id:Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True)
    symbol:Mapped[str]=mapped_column(String(32),nullable=False,index=True)
    bid:Mapped[float|None]=mapped_column(Float);ask:Mapped[float|None]=mapped_column(Float);spread:Mapped[float|None]=mapped_column(Float);spread_percent:Mapped[float|None]=mapped_column(Float);mid_price:Mapped[float|None]=mapped_column(Float)
    bid_volume:Mapped[float|None]=mapped_column(Float);ask_volume:Mapped[float|None]=mapped_column(Float);tick_volume:Mapped[float|None]=mapped_column(Float)
    source:Mapped[str]=mapped_column(String(64),nullable=False);ingestion_timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)

class MarketSessionRecord(Base):
    __tablename__="market_sessions";id:Mapped[int]=mapped_column(Integer,primary_key=True);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);symbol:Mapped[str]=mapped_column(String(32),nullable=False);session:Mapped[str]=mapped_column(String(64),nullable=False);source:Mapped[str]=mapped_column(String(64),nullable=False);ingestion_timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
class DataQualityReportRecord(Base):
    __tablename__="data_quality_reports";id:Mapped[int]=mapped_column(Integer,primary_key=True);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);symbol:Mapped[str]=mapped_column(String(32),nullable=False);timeframe:Mapped[str]=mapped_column(String(8),nullable=False);status:Mapped[str]=mapped_column(String(16),nullable=False);report_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False);source:Mapped[str]=mapped_column(String(64),nullable=False);ingestion_timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
class ProviderStatusRecord(Base):
    __tablename__="provider_status";id:Mapped[int]=mapped_column(Integer,primary_key=True);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);provider:Mapped[str]=mapped_column(String(64),nullable=False);status:Mapped[str]=mapped_column(String(32),nullable=False);metadata_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False);source:Mapped[str]=mapped_column(String(64),nullable=False);ingestion_timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
class InstitutionalObservationRecord(Base):
    __tablename__="institutional_observations";id:Mapped[int]=mapped_column(Integer,primary_key=True);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);asset:Mapped[str]=mapped_column(String(32),nullable=False);provider_status:Mapped[str]=mapped_column(String(32),nullable=False);pressure_proxy:Mapped[float|None]=mapped_column(Float);confidence:Mapped[float]=mapped_column(Float,nullable=False);is_proxy:Mapped[bool]=mapped_column(Boolean,nullable=False,default=True);source:Mapped[str]=mapped_column(String(64),nullable=False);ingestion_timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)
class MarketDatasetRecord(Base):
    __tablename__="market_datasets";dataset_id:Mapped[str]=mapped_column(String(128),primary_key=True);source:Mapped[str]=mapped_column(String(64),nullable=False);symbol:Mapped[str]=mapped_column(String(32),nullable=False);timeframe:Mapped[str]=mapped_column(String(8),nullable=False);start_time:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);end_time:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False);metadata_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False)
class EconomicCalendarEventRecord(Base):
    __tablename__="economic_calendar_events";id:Mapped[int]=mapped_column(Integer,primary_key=True);event:Mapped[str]=mapped_column(String(255),nullable=False);currency:Mapped[str]=mapped_column(String(8),nullable=False);importance:Mapped[str]=mapped_column(String(16),nullable=False);scheduled_time:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);actual:Mapped[float|None]=mapped_column(Float);forecast:Mapped[float|None]=mapped_column(Float);previous:Mapped[float|None]=mapped_column(Float);source:Mapped[str]=mapped_column(String(64),nullable=False);ingestion_timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utcnow,nullable=False)


__all__ = [
    "MarketCandle", "MarketDataIngestion", "MarketTick", "TradingViewAlert", "LiquidityEvent",
    "StructureEvent", "IndicatorSnapshot", "MarketIntelligenceSnapshot", "COTReport", "InstitutionalPressure",
    "StrategySignal", "TradingOutcome", "SimulatedTradeRecord", "MarketFeature",
    "MarketLabel", "DatasetMetadataRecord", "StrategyMarketSnapshot", "TradeSetupRecord",
    "StrategyDecisionRecord", "PredictionRecord", "DCAEventRecord", "ExitDecisionRecord",
    "StrategyBacktestRecord",
    "MarketQuote", "MarketSessionRecord", "DataQualityReportRecord", "ProviderStatusRecord",
    "InstitutionalObservationRecord", "MarketDatasetRecord", "EconomicCalendarEventRecord",
]
