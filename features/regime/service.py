from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import load_yaml
from database.models import COTReport, InstitutionalPressure
from database.repositories import CandleRepository
from features.candles import candle_close_time, candle_value, closed_candle_prefix, utc_aware
from features.indicators import MTFIndicatorEngine
from features.liquidity import LiquidityEngine
from data_sources.resampler import MarketDataResampler
from features.regime.market_regime import InstitutionalFlowInput, MarketRegimeEngine, MarketRegimeSnapshot
from features.session import SessionEngine
from features.structure import MarketStructureEngine


class MarketRegimeService:
    TIMEFRAMES = ("D1", "H4", "H1", "M15", "M5", "M1")

    def __init__(self, session: Session):
        self.session = session
        config = load_yaml()
        phase = config.get("phase_1b", {})
        sessions = config.get("sessions", {})
        regime = config.get("market_regime", {})
        session_engine = SessionEngine(
            timezone=sessions.get("timezone", "UTC"),
            asia=tuple(sessions.get("asia", ("00:00", "09:00"))),
            london=tuple(sessions.get("london", ("07:00", "16:00"))),
            new_york=tuple(sessions.get("new_york", ("13:00", "22:00"))),
        )
        common = {
            "swing_left_bars": int(phase.get("swing_left_bars", 2)),
            "swing_right_bars": int(phase.get("swing_right_bars", 2)),
            "equal_level_tolerance_points": float(phase.get("equal_level_tolerance_points", 3)),
            "point_size": phase.get("point_size", 0.00001),
        }
        self.structure_engine = MarketStructureEngine(**common, break_mode=phase.get("break_mode", "CLOSE_BREAK"))
        self.liquidity_engine = LiquidityEngine(
            **common, minimum_rejection_ratio=float(phase.get("minimum_rejection_ratio", 0.15)),
            session_engine=session_engine,
        )
        self.indicator_engine = MTFIndicatorEngine()
        self.resampler = MarketDataResampler()
        self.institutional_config = config.get("institutional_mtf", {})
        self.regime_engine = MarketRegimeEngine(
            structure_weights=regime.get("structure_weights"),
            ltf_weights=regime.get("ltf_weights"),
        )

    def calculate(self, symbol: str, *, as_of: datetime | None = None) -> MarketRegimeSnapshot:
        symbol = symbol.upper()
        native = {
            timeframe: closed_candle_prefix(CandleRepository(self.session).chronological(
                symbol=symbol, timeframe=timeframe,
            ))
            for timeframe in self.TIMEFRAMES
        }
        if as_of is None:
            latest_times = [candle_close_time(rows[-1]) for rows in native.values() if rows]
            as_of = max(latest_times) if latest_times else datetime.now(timezone.utc)
        as_of = utc_aware(as_of)
        candles = {
            timeframe: [candle for candle in rows if candle_close_time(candle) <= as_of]
            for timeframe, rows in native.items()
        }
        for source_timeframe, target_timeframe in (
            ("M1", "M5"), ("M5", "M15"), ("M15", "H1"),
            ("H1", "H4"), ("H4", "D1"),
        ):
            if not candles[target_timeframe] and candles[source_timeframe]:
                candles[target_timeframe] = self.resampler.resample(
                    candles[source_timeframe], source_timeframe, target_timeframe, as_of=as_of,
                )

        structure = {timeframe: self.structure_engine.calculate(rows) for timeframe, rows in candles.items()}
        liquidity = {timeframe: self.liquidity_engine.calculate(rows) for timeframe, rows in candles.items()}
        indicators = self.indicator_engine.calculate_matrix(candles, as_of=as_of)
        current_rows = candles["M15"] or candles["H1"] or candles["H4"] or candles["D1"]
        current_price = Decimal(str(candle_value(current_rows[-1], "close", 0))) if current_rows else Decimal("0")
        institutional = self._institutional(symbol, as_of)
        return self.regime_engine.calculate(
            symbol=symbol, as_of=as_of,
            available_timeframes=[timeframe for timeframe, rows in candles.items() if rows],
            structure_events=structure, liquidity_events=liquidity,
            indicators=indicators, current_price=current_price,
            institutional=institutional,
        )

    def _institutional(self, symbol: str, as_of: datetime) -> InstitutionalFlowInput | None:
        row = self.session.scalar(select(InstitutionalPressure).where(
            InstitutionalPressure.symbol == symbol,
            InstitutionalPressure.timestamp <= as_of,
        ).order_by(InstitutionalPressure.timestamp.desc()).limit(1))
        if row is None:
            market = self.institutional_config.get("cot_market_mapping", {}).get(symbol)
            if not market:
                return None
            reports = list(self.session.scalars(select(COTReport).where(
                COTReport.market.ilike(f"%{market}%"),
                COTReport.report_date <= as_of.date(),
            ).order_by(COTReport.report_date.desc()).limit(2)))
            if not reports:
                return None
            latest = reports[0]
            long_total = sum(value or 0 for value in (latest.asset_manager_long, latest.leveraged_money_long))
            short_total = sum(value or 0 for value in (latest.asset_manager_short, latest.leveraged_money_short))
            denominator = long_total + short_total
            cot_score = 100.0 * (long_total - short_total) / denominator if denominator else None
            oi_score = None
            if len(reports) == 2 and reports[0].open_interest and reports[1].open_interest:
                oi_score = max(-100.0, min(100.0, 100.0 * (reports[0].open_interest - reports[1].open_interest) / reports[1].open_interest))
            return InstitutionalFlowInput(cot_score=cot_score, cme_open_interest_score=oi_score)
        metadata = row.source_metadata or {}
        return InstitutionalFlowInput(
            cot_score=row.cot_score,
            bank_participation_score=metadata.get("bank_participation_score"),
            cme_volume_score=row.volume_score,
            cme_open_interest_score=row.open_interest_score,
        )
