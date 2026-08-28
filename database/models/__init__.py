from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, true
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
class PaperAccountRecord(Base):
    __tablename__="paper_accounts";account_id:Mapped[str]=mapped_column(String(64),primary_key=True);initial_balance:Mapped[float]=mapped_column(Float,nullable=False);balance:Mapped[float]=mapped_column(Float,nullable=False);equity:Mapped[float]=mapped_column(Float,nullable=False);margin:Mapped[float]=mapped_column(Float,nullable=False);free_margin:Mapped[float]=mapped_column(Float,nullable=False);used_margin:Mapped[float]=mapped_column(Float,nullable=False);realized_pnl:Mapped[float]=mapped_column(Float,nullable=False);unrealized_pnl:Mapped[float]=mapped_column(Float,nullable=False);commission:Mapped[float]=mapped_column(Float,nullable=False);slippage:Mapped[float]=mapped_column(Float,nullable=False);created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
class PaperPositionRecord(Base):
    __tablename__="paper_positions";position_id:Mapped[str]=mapped_column(String(64),primary_key=True);symbol:Mapped[str]=mapped_column(String(32),nullable=False);direction:Mapped[str]=mapped_column(String(8),nullable=False);state:Mapped[str]=mapped_column(String(32),nullable=False);opened_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);position_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False)
class PaperOrderRecord(Base):
    __tablename__="paper_orders";order_id:Mapped[str]=mapped_column(String(64),primary_key=True);position_id:Mapped[str|None]=mapped_column(String(64));symbol:Mapped[str]=mapped_column(String(32),nullable=False);order_type:Mapped[str]=mapped_column(String(16),nullable=False);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);order_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False)
class PaperExecutionRecord(Base):
    __tablename__="paper_executions";id:Mapped[int]=mapped_column(Integer,primary_key=True);order_id:Mapped[str|None]=mapped_column(String(64));timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);accepted:Mapped[bool]=mapped_column(Boolean,nullable=False);rejection_reason:Mapped[str|None]=mapped_column(String(128));execution_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False)
class PaperDCAEventRecord(Base):
    __tablename__="paper_dca_events";dca_id:Mapped[str]=mapped_column(String(64),primary_key=True);position_id:Mapped[str]=mapped_column(String(64),nullable=False);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);event_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False)
class PaperRiskEventRecord(Base):
    __tablename__="paper_risk_events";id:Mapped[int]=mapped_column(Integer,primary_key=True);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);risk_state:Mapped[str]=mapped_column(String(32),nullable=False);reason:Mapped[str|None]=mapped_column(String(128));event_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False)
class PaperTradeJournalRecord(Base):
    __tablename__="paper_trade_journal";trade_id:Mapped[str]=mapped_column(String(64),primary_key=True);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);journal_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False)
class PaperEquitySnapshotRecord(Base):
    __tablename__="paper_equity_snapshots";id:Mapped[int]=mapped_column(Integer,primary_key=True);account_id:Mapped[str]=mapped_column(String(64),nullable=False);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False);equity:Mapped[float]=mapped_column(Float,nullable=False);balance:Mapped[float]=mapped_column(Float,nullable=False);drawdown:Mapped[float]=mapped_column(Float,nullable=False);snapshot_json:Mapped[dict[str,Any]]=mapped_column(JSON,nullable=False)
class DashboardAlertRecord(Base):
    __tablename__="dashboard_alerts";alert_id:Mapped[str]=mapped_column(String(64),primary_key=True);timestamp:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,index=True);symbol:Mapped[str|None]=mapped_column(String(32));alert_type:Mapped[str]=mapped_column(String(64),nullable=False);severity:Mapped[str]=mapped_column(String(16),nullable=False);title:Mapped[str]=mapped_column(String(255),nullable=False);message:Mapped[str]=mapped_column(Text,nullable=False);source:Mapped[str]=mapped_column(String(64),nullable=False);version:Mapped[str]=mapped_column(String(64),nullable=False);data_quality:Mapped[str]=mapped_column(String(16),nullable=False);read:Mapped[bool]=mapped_column(Boolean,nullable=False,default=False);context_json:Mapped[dict[str,Any]|None]=mapped_column(JSON)


# ---------------------------------------------------------------- Phase 10 MT5
# Read-only observation of a DEMO MetaTrader 5 account. No credential is stored:
# there is deliberately no password or secret column anywhere below.


class MT5AccountRecord(Base):
    __tablename__ = "mt5_accounts"
    account_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    login_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    server: Mapped[str | None] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    trade_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    leverage: Mapped[int | None] = mapped_column(Integer)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MT5AccountSnapshotRecord(Base):
    __tablename__ = "mt5_account_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    login_masked: Mapped[str] = mapped_column(String(32), nullable=False)
    broker: Mapped[str] = mapped_column(String(64), nullable=False)
    server: Mapped[str | None] = mapped_column(String(128))
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(16), nullable=False)
    balance: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    margin: Mapped[float] = mapped_column(Float, nullable=False)
    free_margin: Mapped[float] = mapped_column(Float, nullable=False)
    margin_level: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MT5SymbolSnapshotRecord(Base):
    __tablename__ = "mt5_symbol_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    broker_symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    digits: Mapped[int | None] = mapped_column(Integer)
    point: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MT5TickSnapshotRecord(Base):
    __tablename__ = "mt5_tick_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    broker_symbol: Mapped[str | None] = mapped_column(String(64))
    bid: Mapped[float | None] = mapped_column(Float)
    ask: Mapped[float | None] = mapped_column(Float)
    last: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    spread_state: Mapped[str | None] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    tick_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MT5PositionSnapshotRecord(Base):
    __tablename__ = "mt5_position_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ticket: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    profit: Mapped[float] = mapped_column(Float, nullable=False)
    swap: Mapped[float] = mapped_column(Float, nullable=False)
    commission: Mapped[float] = mapped_column(Float, nullable=False)
    magic_number: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comment: Mapped[str | None] = mapped_column(String(255))
    ownership: Mapped[str] = mapped_column(String(16), nullable=False)
    position_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MT5OrderSnapshotRecord(Base):
    __tablename__ = "mt5_order_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ticket: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    order_type: Mapped[str | None] = mapped_column(String(32))
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    price_open: Mapped[float] = mapped_column(Float, nullable=False)
    state: Mapped[str | None] = mapped_column(String(32))
    magic_number: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    ownership: Mapped[str] = mapped_column(String(16), nullable=False)
    order_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MT5ConnectionEventRecord(Base):
    __tablename__ = "mt5_connection_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    server: Mapped[str | None] = mapped_column(String(128))
    login_masked: Mapped[str | None] = mapped_column(String(32))
    reasons: Mapped[str | None] = mapped_column(Text)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MT5DataQualityEventRecord(Base):
    __tablename__ = "mt5_data_quality_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reasons: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# --------------------------------------------------- Phase 11 DEMO execution
# Audit store for gated DEMO execution. No credential column exists here either.


class ExecutionRequestRecord(Base):
    __tablename__ = "execution_requests"
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    order_type: Mapped[str] = mapped_column(String(16), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    price: Mapped[float | None] = mapped_column(Float)
    sl: Mapped[float | None] = mapped_column(Float)
    tp: Mapped[float | None] = mapped_column(Float)
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy_id: Mapped[str | None] = mapped_column(String(64))
    signal_id: Mapped[str | None] = mapped_column(String(64))
    comment: Mapped[str | None] = mapped_column(String(255))
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ExecutionResultRecord(Base):
    __tablename__ = "execution_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    broker_ticket: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    requested_volume: Mapped[float] = mapped_column(Float, nullable=False)
    filled_volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    requested_price: Mapped[float | None] = mapped_column(Float)
    filled_price: Mapped[float | None] = mapped_column(Float)
    sl: Mapped[float | None] = mapped_column(Float)
    tp: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ExecutionAuditLogRecord(Base):
    __tablename__ = "execution_audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    approved: Mapped[bool | None] = mapped_column(Boolean)
    reasons: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ReconciliationRecordRow(Base):
    __tablename__ = "reconciliation_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    broker_ticket: Mapped[int | None] = mapped_column(BigInteger)
    symbol: Mapped[str | None] = mapped_column(String(32))
    reasons: Mapped[str | None] = mapped_column(Text)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class KillSwitchEventRecord(Base):
    __tablename__ = "kill_switch_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    engaged: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# ------------------------------------------- Phase 12 observation / validation
# Forward-observation records. Nothing here implies an order was ever placed:
# execution_simulations carries orders_sent, which is always 0 in Phase 12.


class ObservationMarketSnapshotRecord(Base):
    __tablename__ = "observation_market_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    regime: Mapped[str | None] = mapped_column(String(16))
    session: Mapped[str | None] = mapped_column(String(32))
    mid_price: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="mt5")
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FeatureSnapshotRecord(Base):
    __tablename__ = "feature_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    regime: Mapped[str | None] = mapped_column(String(16))
    signal: Mapped[str | None] = mapped_column(String(16))
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="mt5")
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ExecutionSimulationRecord(Base):
    __tablename__ = "execution_simulations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    simulation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    cycle_id: Mapped[str | None] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signal: Mapped[str] = mapped_column(String(16), nullable=False)
    risk: Mapped[str] = mapped_column(String(16), nullable=False)
    execution: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    observation_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    orders_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    simulation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class SystemHealthRecord(Base):
    __tablename__ = "system_health"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    cycle_id: Mapped[str | None] = mapped_column(String(64), index=True)
    last_error: Mapped[str | None] = mapped_column(Text)
    health_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class MT5HealthEventRecord(Base):
    __tablename__ = "mt5_health_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    login_masked: Mapped[str | None] = mapped_column(String(32))
    broker: Mapped[str | None] = mapped_column(String(64))
    server: Mapped[str | None] = mapped_column(String(128))
    account_type: Mapped[str | None] = mapped_column(String(16))
    terminal_build: Mapped[int | None] = mapped_column(Integer)
    reasons: Mapped[str | None] = mapped_column(Text)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ObservationPerformanceRecord(Base):
    __tablename__ = "observation_performance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Phase 13: an observation is the unit a label is later attached to.
    observation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signal: Mapped[str] = mapped_column(String(16), nullable=False)
    entry: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Float)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    mae: Mapped[float | None] = mapped_column(Float)
    mfe: Mapped[float | None] = mapped_column(Float)
    hypothetical_pnl: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    session: Mapped[str | None] = mapped_column(String(32))
    regime: Mapped[str | None] = mapped_column(String(16))
    nn_confidence: Mapped[float | None] = mapped_column(Float)
    strategy_confidence: Mapped[float | None] = mapped_column(Float)
    dca_state: Mapped[str | None] = mapped_column(String(32))
    future_price: Mapped[float | None] = mapped_column(Float)
    future_return: Mapped[float | None] = mapped_column(Float)
    nn_probability: Mapped[float | None] = mapped_column(Float)
    strategy_decision: Mapped[str | None] = mapped_column(String(24))
    horizon: Mapped[str | None] = mapped_column(String(16))
    label_version: Mapped[str | None] = mapped_column(String(64))
    # Forward observation, never a backtest and never a real fill.
    observed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    record_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# ------------------------------------------------ Phase 13 learning pipeline
# Metadata only. Model artifacts live on disk under phase_13.artifacts_path and
# are gitignored; no table here stores a binary or a credential.


class DatasetAuditRecord(Base):
    __tablename__ = "dataset_audits"
    dataset_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    label_version: Mapped[str] = mapped_column(String(64), nullable=False)
    preprocessing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon: Mapped[str | None] = mapped_column(String(16))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    symbols: Mapped[str] = mapped_column(String(255), nullable=False)
    timeframes: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_values: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    class_distribution: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    audit_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ModelRegistryRecord(Base):
    __tablename__ = "model_registry"
    model_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    task_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    label_version: Mapped[str] = mapped_column(String(64), nullable=False)
    training_dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    preprocessing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    training_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    edge_verdict: Mapped[str] = mapped_column(String(24), nullable=False, default="NO_EDGE")
    artifact_path: Mapped[str | None] = mapped_column(String(512))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ModelDriftEventRecord(Base):
    __tablename__ = "model_drift_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    model_id: Mapped[str | None] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    metric: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Constant "FLAG_ONLY": detection never triggers retraining or promotion.
    action: Mapped[str] = mapped_column(String(24), nullable=False, default="FLAG_ONLY")
    detail: Mapped[str | None] = mapped_column(Text)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class RetrainingRequestRecord(Base):
    __tablename__ = "retraining_requests"
    request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    triggers: Mapped[str] = mapped_column(String(255), nullable=False)
    reasons: Mapped[str | None] = mapped_column(Text)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    model_id: Mapped[str | None] = mapped_column(String(64), index=True)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# ------------------------------------------- Phase 14 forward observation loop
# Records of what the loop observed and concluded. No table here holds an order,
# a broker ticket, a credential or a model binary.


class ObservationRecord(Base):
    __tablename__ = "observations"
    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # Deterministic: sha256(symbol|timeframe|candle). A restart reproduces it, so
    # re-running the same candle is a duplicate rather than a second observation.
    cycle_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_price: Mapped[float | None] = mapped_column(Float)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="WAIT")
    strategy: Mapped[str | None] = mapped_column(String(32))
    market_regime: Mapped[str | None] = mapped_column(String(24))
    session: Mapped[str | None] = mapped_column(String(32))
    feature_version: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    nn_confidence: Mapped[float | None] = mapped_column(Float)
    risk_state: Mapped[str | None] = mapped_column(String(16))
    observation_horizon: Mapped[str] = mapped_column(String(16), nullable=False, default="1h")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ObservationOutcomeRecord(Base):
    __tablename__ = "observation_outcomes"
    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    future_price: Mapped[float] = mapped_column(Float, nullable=False)
    future_return: Mapped[float] = mapped_column(Float, nullable=False)
    mfe: Mapped[float | None] = mapped_column(Float)
    mae: Mapped[float | None] = mapped_column(Float)
    hypothetical_pnl: Mapped[float | None] = mapped_column(Float)
    # The primary performance metric (section 7): gross is never the headline.
    net_hypothetical_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    holding_time: Mapped[float | None] = mapped_column(Float)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    regime: Mapped[str | None] = mapped_column(String(24))
    session: Mapped[str | None] = mapped_column(String(32))
    timeframe: Mapped[str | None] = mapped_column(String(16))
    label_version: Mapped[str | None] = mapped_column(String(64))
    # Section 24: never a backtest, never an executed fill.
    evidence: Mapped[str] = mapped_column(String(32), nullable=False, default="FORWARD_OBSERVATION")
    outcome_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ModelErrorRecord(Base):
    __tablename__ = "model_errors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    observation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model_id: Mapped[str | None] = mapped_column(String(64), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    predicted: Mapped[str] = mapped_column(String(16), nullable=False)
    actual: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    error_class: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    tags: Mapped[str | None] = mapped_column(String(255))
    high_confidence_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    regime: Mapped[str | None] = mapped_column(String(24))
    session: Mapped[str | None] = mapped_column(String(32))
    error_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ModelPerformanceRecord(Base):
    __tablename__ = "model_performance"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str | None] = mapped_column(String(64), index=True)
    model_version: Mapped[str | None] = mapped_column(String(64))
    window: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reliable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    win_rate: Mapped[float | None] = mapped_column(Float)
    expectancy: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    average_mae: Mapped[float | None] = mapped_column(Float)
    average_mfe: Mapped[float | None] = mapped_column(Float)
    prediction_accuracy: Mapped[float | None] = mapped_column(Float)
    brier_score: Mapped[float | None] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(String(32), nullable=False, default="FORWARD_OBSERVATION")
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class EdgeEvaluationRecord(Base):
    __tablename__ = "edge_evaluations"
    evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str | None] = mapped_column(String(64), index=True)
    symbol: Mapped[str | None] = mapped_column(String(32), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expectancy: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    beats_baselines: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reasons: Mapped[str | None] = mapped_column(Text)
    # Section 24: an edge may only be claimed from forward evidence.
    evidence: Mapped[str] = mapped_column(String(32), nullable=False, default="FORWARD_OBSERVATION")
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class TrainingRunRecord(Base):
    __tablename__ = "training_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    model_id: Mapped[str | None] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dataset_id: Mapped[str | None] = mapped_column(String(128), index=True)
    trigger: Mapped[str | None] = mapped_column(String(32))
    requested_by: Mapped[str | None] = mapped_column(String(128))
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    failed_step: Mapped[str | None] = mapped_column(String(24))
    state: Mapped[str | None] = mapped_column(String(16))
    edge_verdict: Mapped[str | None] = mapped_column(String(24))
    registered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Constant false: a training run never promotes. Promotion is a separate,
    # human-approved action.
    promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    run_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# ------------------------------------------------ Phase 15 AI research lab
# Declarations and measurements. A strategy row is a description of rules, not
# an executable object, and an experiment row is a recorded comparison.


class ResearchStrategyRecord(Base):
    __tablename__ = "research_strategies"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Content hash of the rule declaration: two identical strategies collide.
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    features: Mapped[str | None] = mapped_column(Text)
    timeframes: Mapped[str | None] = mapped_column(String(255))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    record_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ResearchExperimentRecord(Base):
    __tablename__ = "research_experiments"
    experiment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    strategy_key: Mapped[str | None] = mapped_column(String(128), index=True)
    strategy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(64))
    dataset_version: Mapped[str | None] = mapped_column(String(128), index=True)
    label_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expectancy: Mapped[float | None] = mapped_column(Float)
    win_rate: Mapped[float | None] = mapped_column(Float)
    net_pnl: Mapped[float | None] = mapped_column(Float)
    profit_factor: Mapped[float | None] = mapped_column(Float)
    maximum_drawdown: Mapped[float | None] = mapped_column(Float)
    sharpe_like: Mapped[float | None] = mapped_column(Float)
    reliable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Section 6: research reads forward evidence and records which kind it used.
    evidence: Mapped[str] = mapped_column(String(32), nullable=False, default="FORWARD_OBSERVATION")
    # Section 17: whether this result touched the reserved holdout.
    used_holdout: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ResearchFindingRecord(Base):
    __tablename__ = "research_findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    study: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effect_size: Mapped[float | None] = mapped_column(Float)
    significant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    experiment_id: Mapped[str | None] = mapped_column(String(64), index=True)
    reasons: Mapped[str | None] = mapped_column(Text)
    finding_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# ------------------------------------------- Phase 16 controlled DEMO trading
# Execution proposals, the DEMO trade journal, the trading-day risk budget,
# position monitoring, paper-vs-DEMO comparisons and emergency events.
# As everywhere else in this schema, no table here has a credential column.


class DemoExecutionProposalRecord(Base):
    __tablename__ = "demo_execution_proposals"
    proposal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approval_reason: Mapped[str | None] = mapped_column(String(255))
    rejected_reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    blocked_by: Mapped[str | None] = mapped_column(Text)
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DemoTradeJournalRecord(Base):
    __tablename__ = "demo_trade_journal"
    trade_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    broker_ticket: Mapped[int | None] = mapped_column(BigInteger)
    exit_reason: Mapped[str | None] = mapped_column(String(48), index=True)
    pnl: Mapped[float | None] = mapped_column(Float)
    gross_pnl: Mapped[float | None] = mapped_column(Float)
    mae: Mapped[float | None] = mapped_column(Float)
    mfe: Mapped[float | None] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    swap: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage: Mapped[float | None] = mapped_column(Float)
    session: Mapped[str | None] = mapped_column(String(32))
    regime: Mapped[str | None] = mapped_column(String(32))
    model_version: Mapped[str | None] = mapped_column(String(64))
    strategy_version: Mapped[str | None] = mapped_column(String(64))
    feature_version: Mapped[str | None] = mapped_column(String(64))
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    journal_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DemoDailyRiskRecord(Base):
    __tablename__ = "demo_daily_risk"
    __table_args__ = (UniqueConstraint("trading_day", "timezone", name="uq_demo_daily_risk_day"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trading_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    starting_equity: Mapped[float] = mapped_column(Float, nullable=False)
    equity: Mapped[float] = mapped_column(Float, nullable=False)
    peak_equity: Mapped[float] = mapped_column(Float, nullable=False)
    daily_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    daily_drawdown: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_drawdown: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trade_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reasons: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DemoPositionSnapshotRecord(Base):
    __tablename__ = "demo_position_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    current_price: Mapped[float] = mapped_column(Float, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mae: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mfe: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dca_levels: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DemoPaperComparisonRecord(Base):
    __tablename__ = "demo_paper_comparisons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    paper_entry: Mapped[float | None] = mapped_column(Float)
    demo_entry: Mapped[float | None] = mapped_column(Float)
    paper_exit: Mapped[float | None] = mapped_column(Float)
    demo_exit: Mapped[float | None] = mapped_column(Float)
    entry_difference: Mapped[float | None] = mapped_column(Float)
    exit_difference: Mapped[float | None] = mapped_column(Float)
    spread: Mapped[float | None] = mapped_column(Float)
    slippage: Mapped[float | None] = mapped_column(Float)
    commission: Mapped[float | None] = mapped_column(Float)
    swap: Mapped[float | None] = mapped_column(Float)
    pnl_difference: Mapped[float | None] = mapped_column(Float)
    within_tolerance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    errors: Mapped[str | None] = mapped_column(Text)
    comparison_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class DemoEmergencyEventRecord(Base):
    __tablename__ = "demo_emergency_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    triggers: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str | None] = mapped_column(String(48))
    shutdown: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Always False: an emergency engages the kill switch, it never liquidates.
    positions_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# ----------------------------------------- Phase 17 shadow trading & validation
# Shadow rows are counterfactuals, never fills: `orders_sent` is a column that is
# always 0, so the invariant is visible in the data and not only in prose.


class ShadowSignalRecord(Base):
    __tablename__ = "shadow_signals"
    shadow_signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    demo_execution_request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    entry: Mapped[float | None] = mapped_column(Float)
    stop_loss: Mapped[float | None] = mapped_column(Float)
    take_profit: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    strategy: Mapped[str | None] = mapped_column(String(64))
    strategy_version: Mapped[str | None] = mapped_column(String(64))
    model_version: Mapped[str | None] = mapped_column(String(64))
    feature_version: Mapped[str | None] = mapped_column(String(64))
    confidence: Mapped[float | None] = mapped_column(Float)
    risk_snapshot_id: Mapped[str | None] = mapped_column(String(64))
    risk_state: Mapped[str | None] = mapped_column(String(16))
    session: Mapped[str | None] = mapped_column(String(32), index=True)
    regime: Mapped[str | None] = mapped_column(String(32), index=True)
    timeframe: Mapped[str | None] = mapped_column(String(8))
    signal_timeframe: Mapped[str | None] = mapped_column(String(8))
    spread: Mapped[float | None] = mapped_column(Float)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Would the trade have been taken had execution been armed?
    decision_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False,
                                                    index=True)
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    not_executed_reason: Mapped[str | None] = mapped_column(String(64))
    blocked_reasons: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN", index=True)
    # Always 0. A shadow signal has no transport to send anything with.
    orders_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signal_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ShadowOutcomeRecord(Base):
    __tablename__ = "shadow_outcomes"
    shadow_signal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    expected_entry: Mapped[float] = mapped_column(Float, nullable=False)
    expected_exit: Mapped[float] = mapped_column(Float, nullable=False)
    expected_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    mfe: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mae: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    spread: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    slippage_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    commission_estimate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    net_expected_pnl: Mapped[float] = mapped_column(Float, nullable=False)
    exit_reason: Mapped[str | None] = mapped_column(String(48))
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    session: Mapped[str | None] = mapped_column(String(32), index=True)
    regime: Mapped[str | None] = mapped_column(String(32), index=True)
    outcome_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ShadowDemoComparisonRecord(Base):
    __tablename__ = "demo_comparisons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    shadow_signal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    demo_execution_request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signal_difference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    entry_difference: Mapped[float | None] = mapped_column(Float)
    exit_difference: Mapped[float | None] = mapped_column(Float)
    slippage_difference: Mapped[float | None] = mapped_column(Float)
    cost_difference: Mapped[float | None] = mapped_column(Float)
    pnl_difference: Mapped[float | None] = mapped_column(Float)
    mae_difference: Mapped[float | None] = mapped_column(Float)
    mfe_difference: Mapped[float | None] = mapped_column(Float)
    time_difference: Mapped[float | None] = mapped_column(Float)
    primary_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kinds: Mapped[str | None] = mapped_column(Text)
    matched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    shadow_net_pnl: Mapped[float | None] = mapped_column(Float)
    demo_net_pnl: Mapped[float | None] = mapped_column(Float)
    comparison_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ExecutionQualityRecord(Base):
    __tablename__ = "execution_quality"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    window: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    submitted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errored: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fill_rate: Mapped[float | None] = mapped_column(Float)
    rejection_rate: Mapped[float | None] = mapped_column(Float)
    average_slippage: Mapped[float | None] = mapped_column(Float)
    worst_slippage: Mapped[float | None] = mapped_column(Float)
    reconciliation_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    connection_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reliable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ValidationRunRecord(Base):
    __tablename__ = "validation_runs"
    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    window: Mapped[str | None] = mapped_column(String(16))
    samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_status: Mapped[str] = mapped_column(String(24), nullable=False, default="INSUFFICIENT_DATA")
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reasons: Mapped[str | None] = mapped_column(Text)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PerformanceGateRecord(Base):
    __tablename__ = "performance_gates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    gate: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    observed: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str | None] = mapped_column(Text)
    # Always False. A passing gate is evidence, never an action.
    enabled_execution: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gate_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class CircuitBreakerEventRecord(Base):
    __tablename__ = "circuit_breaker_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    triggers: Mapped[str | None] = mapped_column(Text)
    reasons: Mapped[str | None] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    # Always False: tripping the breaker blocks new orders, it never liquidates.
    positions_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    health_check: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_check: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    account_validation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    event_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


__all__ = [
    "MarketCandle", "MarketDataIngestion", "MarketTick", "TradingViewAlert", "LiquidityEvent",
    "StructureEvent", "IndicatorSnapshot", "MarketIntelligenceSnapshot", "COTReport", "InstitutionalPressure",
    "StrategySignal", "TradingOutcome", "SimulatedTradeRecord", "MarketFeature",
    "MarketLabel", "DatasetMetadataRecord", "StrategyMarketSnapshot", "TradeSetupRecord",
    "StrategyDecisionRecord", "PredictionRecord", "DCAEventRecord", "ExitDecisionRecord",
    "StrategyBacktestRecord",
    "MarketQuote", "MarketSessionRecord", "DataQualityReportRecord", "ProviderStatusRecord",
    "InstitutionalObservationRecord", "MarketDatasetRecord", "EconomicCalendarEventRecord",
    "PaperAccountRecord", "PaperPositionRecord", "PaperOrderRecord", "PaperExecutionRecord",
    "PaperDCAEventRecord", "PaperRiskEventRecord", "PaperTradeJournalRecord", "PaperEquitySnapshotRecord",
    "DashboardAlertRecord",
    "MT5AccountRecord", "MT5AccountSnapshotRecord", "MT5SymbolSnapshotRecord",
    "MT5TickSnapshotRecord", "MT5PositionSnapshotRecord", "MT5OrderSnapshotRecord",
    "MT5ConnectionEventRecord", "MT5DataQualityEventRecord",
    "ExecutionRequestRecord", "ExecutionResultRecord", "ExecutionAuditLogRecord",
    "ReconciliationRecordRow", "KillSwitchEventRecord",
    "ObservationMarketSnapshotRecord", "FeatureSnapshotRecord", "ExecutionSimulationRecord",
    "SystemHealthRecord", "MT5HealthEventRecord", "ObservationPerformanceRecord",
    "DatasetAuditRecord", "ModelRegistryRecord", "ModelDriftEventRecord",
    "ObservationRecord", "ObservationOutcomeRecord", "ModelErrorRecord",
    "ResearchStrategyRecord", "ResearchExperimentRecord", "ResearchFindingRecord",
    "ModelPerformanceRecord", "EdgeEvaluationRecord", "TrainingRunRecord",
    "RetrainingRequestRecord",
    "DemoExecutionProposalRecord", "DemoTradeJournalRecord", "DemoDailyRiskRecord",
    "DemoPositionSnapshotRecord", "DemoPaperComparisonRecord", "DemoEmergencyEventRecord",
    "ShadowSignalRecord", "ShadowOutcomeRecord", "ShadowDemoComparisonRecord",
    "ExecutionQualityRecord", "ValidationRunRecord", "PerformanceGateRecord",
    "CircuitBreakerEventRecord",
]
