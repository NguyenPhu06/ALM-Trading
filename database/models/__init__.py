from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MarketCandle(Base):
    __tablename__ = "market_candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_market_candle"),
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
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


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


__all__ = [
    "MarketCandle", "MarketTick", "TradingViewAlert", "LiquidityEvent",
    "StructureEvent", "IndicatorSnapshot", "COTReport", "InstitutionalPressure",
    "StrategySignal", "TradingOutcome",
]
